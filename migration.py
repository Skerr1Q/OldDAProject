#!/usr/bin/env python3
"""Run with authenticated gh + git; --workdir must be durable and have ample free space.
GitHub scopes: repo + read:project; delete_repo for deletion, workflow if needed for old workflows.
python github_repo_migration.py --workdir PATH                   # local backups/build
python github_repo_migration.py --workdir PATH --publish         # private destinations
python github_repo_migration.py --workdir PATH --publish --delete-originals
"""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

OWNER = 'Skerr1Q'
GROUPS = {
    'OldDAProject': ['AirBNB_NYC_DA', 'Amazon-DA', 'Spotify-DA', 'ZNO-Database', 'WorkUaScraper'],
    'OldSchoolProject': ['DBIS-Course', 'Intro-To-Databases', 'Optimization-Methods-Course-Project',
                         'NQueens', 'SudokuSolver', 'IdleGame', 'ShortMovies'],
}
KNOWN_PR_HEAD = 'e53d71b4557fd66e57cb9a3cd81935d067d37c1f'
BROWSER_TARGET_IDS = {'OldDAProject': 1403729764, 'OldSchoolProject': 1403730371}
MAX_BACKUP_BYTES = 100_000_000
ENV = dict(os.environ, GIT_TERMINAL_PROMPT='0', GH_PROMPT_DISABLED='1')


def run(args, cwd=None, data=None, binary=False, check=True):
    result = subprocess.run(args, cwd=cwd, input=data, capture_output=True,
                            text=not binary, env=ENV)
    if check and result.returncode:
        # Avoid printing credential helpers, tokens or authenticated URLs in failures.
        raise RuntimeError(f'{args[0]} {args[1]} failed (exit {result.returncode}); no credentials printed')
    return result.stdout if check else result


def git(args, cwd=None, **kwargs):
    return run(['git', '-c', 'credential.helper=', '-c',
                'credential.helper=!gh auth git-credential', '-c',
                'credential.interactive=false', *args], cwd=cwd, **kwargs)


def api(endpoint, method='GET', fields=None, raw=False):
    args = ['gh', 'api', '--hostname', 'github.com', '--method', method, endpoint]
    for key, value in (fields or {}).items():
        args += ['-F' if isinstance(value, bool) else '-f',
                 f'{key}={str(value).lower() if isinstance(value, bool) else value}']
    output = run(args)
    return output if raw else (json.loads(output) if output.strip() else None)


def pages(endpoint):
    result, number = [], 1
    while True:
        page = api(f'{endpoint}{"&" if "?" in endpoint else "?"}per_page=100&page={number}')
        if not isinstance(page, list):
            raise RuntimeError(f'Unexpected API response: {endpoint}')
        result.extend(page)
        if len(page) < 100:
            return result
        number += 1


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(value, indent=2, sort_keys=True) + '\n', encoding='utf-8')
    os.replace(temp, path)


def digest(path):
    h = hashlib.sha256()
    with open(path, 'rb') as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def ref_map(path):
    return dict(line.split(' ', 1) for line in git(
        ['for-each-ref', '--format=%(refname) %(objectname)'], path).splitlines())


def remote_refs(name):
    return {ref: sha for sha, ref in (line.split('\t') for line in git(
        ['ls-remote', '--refs', f'https://github.com/{OWNER}/{name}.git']).splitlines())}


def export_metadata(name):
    base = f'repos/{OWNER}/{name}'
    repo = api(base)
    repo.pop('temp_clone_token', None)
    if repo.get('owner', {}).get('login') != OWNER or not repo.get('private'):
        raise RuntimeError(f'{name}: owner/private status differs from the approved inventory')
    if repo.get('has_wiki') or repo.get('forks_count', 0) or repo.get('has_discussions'):
        raise RuntimeError(f'{name}: wiki/fork/discussion handling requires a dedicated backup')
    releases = pages(base + '/releases')
    if releases:
        raise RuntimeError(f'{name}: unexpected release assets; stop before migrating')
    query = ('query { repository(owner:"' + OWNER + '",name:"' + name + '") '
             '{ projectsV2(first:100) { nodes { id title } pageInfo { hasNextPage } } } }')
    projects = api('graphql', 'POST', {'query': query})
    if projects.get('errors'):
        raise RuntimeError(f'{name}: project inspection failed; resolve gh permissions first')
    projects = projects['data']['repository']['projectsV2']
    if projects['nodes'] or projects['pageInfo']['hasNextPage']:
        raise RuntimeError(f'{name}: unexpected project assets require a dedicated backup')
    issues = pages(base + '/issues?state=all')
    pulls = pages(base + '/pulls?state=all')
    if any('pull_request' not in item for item in issues):
        raise RuntimeError(f'{name}: unexpected issues require review')
    expected = [1] if name == 'ShortMovies' else []
    if sorted(p['number'] for p in pulls) != expected or sorted(i['number'] for i in issues) != expected:
        raise RuntimeError(f'{name}: unexpected pull requests require review')
    details = {}
    for item in pulls:
        number = item['number']
        pr = api(base + f'/pulls/{number}')
        if (pr['title'] != 'CVE-2007-4559 Patch' or pr['state'] != 'open'
                or pr['head']['sha'] != KNOWN_PR_HEAD):
            raise RuntimeError(f'{name}: known PR #1 changed; review it before migration')
        patch = run(['gh', 'api', '--hostname', 'github.com', '-H',
                     'Accept: application/vnd.github.patch', base + f'/pulls/{number}'])
        details[str(number)] = {
            'issue': api(base + f'/issues/{number}'), 'pull': pr, 'patch': patch,
            'comments': pages(base + f'/issues/{number}/comments'),
            'timeline': pages(base + f'/issues/{number}/timeline'),
            'reviews': pages(base + f'/pulls/{number}/reviews'),
            'review_comments': pages(base + f'/pulls/{number}/comments'),
            'commits': pages(base + f'/pulls/{number}/commits'),
            'files': pages(base + f'/pulls/{number}/files'),
        }
    return {'repository': repo, 'releases': releases, 'projects': projects,
            'issues': issues, 'pulls': pulls, 'details': details,
            'branches': pages(base + '/branches'), 'tags': pages(base + '/tags')}


def reject_lfs(mirror):
    objects = git(['rev-list', '--objects', '--all'], mirror).splitlines()
    checks = git(['cat-file', '--batch-check=%(objectname) %(objecttype) %(objectsize)'],
                 mirror, data='\n'.join(line.split(' ', 1)[0] for line in objects) + '\n')
    candidates = {line.split()[0] for line in checks.splitlines()
                  if len(line.split()) == 3 and line.split()[1] == 'blob'
                  and int(line.split()[2]) <= 1024}
    candidates.update(line.split(' ', 1)[0] for line in objects
                      if line.endswith('/.gitattributes') or line.endswith(' .gitattributes'))
    if candidates:
        blobs = git(['cat-file', '--batch'], mirror,
                    data=('\n'.join(sorted(candidates)) + '\n').encode(), binary=True)
        if b'version https://git-lfs.github.com/spec/v1' in blobs or b'filter=lfs' in blobs:
            raise RuntimeError(f'{mirror.name}: historical LFS content requires a dedicated migration')


def archive_ref(name, ref):
    if ref.startswith('refs/tags/'):
        return 'refs/tags/archive/' + name + '/' + ref[len('refs/tags/'):]
    if ref.startswith('refs/heads/') or ref.startswith('refs/pull/'):
        return 'refs/heads/archive/' + name + '/' + ref[len('refs/'):]
    raise RuntimeError(f'{name}: unsupported source ref {ref}')


def build_target(path, names, sources, root, browser_target=None):
    path.mkdir()
    git(['init', '--initial-branch=main'], path)
    git(['config', 'commit.gpgsign', 'false'], path)
    git(['config', 'user.name', 'GitHub Archive Migration'], path)
    git(['config', 'user.email', f'{OWNER}@users.noreply.github.com'], path)
    metadata = path / '__migration__'
    shutil.copytree(root / 'metadata', metadata)
    write_json(metadata / 'manifest.json', {n: sources[n] for n in names})
    if browser_target is not None:
        (metadata / 'backups').mkdir()
        for name in names:
            bundle = root / 'backups' / (name + '.bundle')
            if bundle.stat().st_size >= MAX_BACKUP_BYTES or digest(bundle) != sources[name]['bundle_sha256']:
                raise RuntimeError(f'{name}: bundle is too large or checksum differs; publishing stopped')
            shutil.copyfile(bundle, metadata / 'backups' / bundle.name)
    rows = '\n'.join(f'- [{n}]({n}/)' for n in names)
    (path / 'README.md').write_text(
        f'# {path.name}\n\nArchived private projects; original default-branch files are preserved.\n\n{rows}\n\n'
        'Original branches, tags and PR refs are preserved under `archive/<project>/`. '
        'Git history remains reachable from main and archive refs. Source metadata and PR '
        'comments/reviews/patches are in `__migration__`; issues/PRs are exports, not native GitHub threads. '
        'The ShortMovies security PR is preserved and is not merged. Gitlinks, including DBIS-Course '
        'gitlinks without .gitmodules, are unchanged; submodule repositories are not included.\n', encoding='utf-8')
    git(['add', 'README.md', '__migration__'], path)
    git(['commit', '-m', 'Document legacy project migration and metadata'], path)
    if browser_target and browser_target['refs']:
        expected = browser_target['refs']['refs/heads/main']
        git(['fetch', '--no-tags', f'https://github.com/{OWNER}/{path.name}.git',
             '+refs/heads/main:refs/bootstrap/main'], path)
        if git(['rev-parse', 'refs/bootstrap/main'], path).strip() != expected:
            raise RuntimeError(f'{path.name}: bootstrap changed during fetch')
        files = git(['ls-tree', '-r', '--name-only', expected], path).splitlines()
        if set(files) != set(browser_target['allowed_paths']):
            raise RuntimeError(f'{path.name}: bootstrap contains unapproved setup files')
        git(['merge', '-s', 'ours', '--allow-unrelated-histories', '--no-commit', expected], path)
        git(['commit', '-m', 'Preserve approved Codespaces setup history'], path)
        git(['update-ref', '-d', 'refs/bootstrap/main'], path)
    for name in names:
        source = sources[name]
        mirror = root / 'mirrors' / (name + '.git')
        git(['fetch', '--no-tags', str(mirror), '+refs/*:refs/migration/*'], path)
        git(['merge', '-s', 'ours', '--allow-unrelated-histories', '--no-commit', source['head']], path)
        git(['read-tree', '--prefix=' + name + '/', '-u', source['head']], path)
        git(['commit', '-m', f'Import {name} with original history'], path)
        for old, sha in source['refs'].items():
            git(['update-ref', archive_ref(name, old), sha], path)
        for ref in ref_map(path):
            if ref.startswith('refs/migration/'):
                git(['update-ref', '-d', ref], path)
    git(['fsck', '--full'], path)
    verify_target(path, names, sources)
    return {'head': git(['rev-parse', 'main'], path).strip(), 'refs': ref_map(path)}


def verify_target(path, names, sources):
    for name in names:
        source = sources[name]
        tree = git(['rev-parse', f'main:{name}'], path).strip()
        if tree != source['tree']:
            raise RuntimeError(f'{name}: destination subtree differs from the source')
        git(['merge-base', '--is-ancestor', source['head'], 'main'], path)
        for old, sha in source['refs'].items():
            if git(['rev-parse', archive_ref(name, old)], path).strip() != sha:
                raise RuntimeError(f'{name}: archive ref verification failed')


def prepare(root, browser_config=None):
    sources = {}
    (root / 'mirrors').mkdir()
    (root / 'backups').mkdir()
    (root / 'metadata').mkdir()
    (root / 'targets').mkdir()
    for name in sum(GROUPS.values(), []):
        print(f'Backing up {name}', flush=True)
        meta = export_metadata(name)
        write_json(root / 'metadata' / (name + '.json'), meta)
        before = remote_refs(name)
        mirror = root / 'mirrors' / (name + '.git')
        git(['clone', '--mirror', f'https://github.com/{OWNER}/{name}.git', str(mirror)])
        git(['fetch', 'origin', '+refs/pull/*/head:refs/pull/*/head',
             '+refs/pull/*/merge:refs/pull/*/merge'], mirror)
        if before != remote_refs(name):
            raise RuntimeError(f'{name}: source changed during backup')
        reject_lfs(mirror)
        git(['fsck', '--full'], mirror)
        branch = meta['repository']['default_branch']
        head = git(['rev-parse', 'refs/heads/' + branch], mirror).strip()
        bundle = root / 'backups' / (name + '.bundle')
        git(['bundle', 'create', str(bundle), '--all'], mirror)
        git(['bundle', 'verify', str(bundle)], mirror)
        sources[name] = {'head': head, 'tree': git(['rev-parse', head + '^{tree}'], mirror).strip(),
                         'refs': ref_map(mirror), 'remote_refs': before,
                         'bundle_sha256': digest(bundle),
                         'metadata_sha256': digest(root / 'metadata' / (name + '.json'))}
    targets = {name: build_target(root / 'targets' / name, members, sources, root,
                                  browser_config['targets'][name] if browser_config else None)
               for name, members in GROUPS.items()}
    plan = {'version': 1, 'owner': OWNER, 'groups': GROUPS, 'sources': sources, 'targets': targets}
    if browser_config:
        plan['browser_config'] = browser_config
    write_json(root / 'plan.json', plan)
    return plan


def fresh_source_check(name, source, root):
    if source['remote_refs'] != remote_refs(name):
        raise RuntimeError(f'{name}: source refs changed since backup')
    expected = json.loads((root / 'metadata' / (name + '.json')).read_text(encoding='utf-8'))
    def comparable(value):
        value = json.loads(json.dumps(value))
        def stable(item):
            if isinstance(item, dict):
                return {key: stable(val) for key, val in item.items()
                        if key not in ('updated_at', 'pushed_at', 'mergeable', 'rebaseable', 'mergeable_state', 'merge_commit_sha')}
            return [stable(val) for val in item] if isinstance(item, list) else item
        return stable(value)
    if comparable(expected) != comparable(export_metadata(name)):
        raise RuntimeError(f'{name}: source metadata changed since backup')



def adopt_empty_target(name, remote):
    if (name not in GROUPS or remote.get('name') != name
            or remote.get('full_name') != f'{OWNER}/{name}'
            or remote.get('owner', {}).get('login') != OWNER or not remote.get('private')
            or remote.get('fork') or remote.get('archived') or remote.get('size') != 0):
        raise RuntimeError(f'{name}: adoption requires an empty, private approved destination')
    base = f'repos/{OWNER}/{name}'
    if remote_refs(name) or any(pages(base + suffix) for suffix in
                              ('/issues?state=all', '/pulls?state=all', '/releases')):
        raise RuntimeError(f'{name}: existing destination has content; refusing adoption')
    query = ('query { repository(owner:"' + OWNER + '",name:"' + name + '") '
             '{ projectsV2(first:1) { nodes { id } pageInfo { hasNextPage } } '
             'discussions(first:1) { totalCount } } }')
    data = api('graphql', 'POST', {'query': query})
    if data.get('errors'):
        raise RuntimeError(f'{name}: adoption asset inspection failed')
    assets = data['data']['repository']
    if (assets['projectsV2']['nodes'] or assets['projectsV2']['pageInfo']['hasNextPage']
            or assets['discussions']['totalCount']):
        raise RuntimeError(f'{name}: existing destination has project/discussion content')
    return {'id': remote['id'], 'adopted': True}


def load_browser_config(path):
    config = json.loads(path.read_text(encoding='utf-8'))
    if config.get('version') != 1 or config.get('owner') != OWNER or set(config.get('targets', {})) != set(GROUPS):
        raise RuntimeError('Destination config does not match the approved browser migration')
    for name, target in config['targets'].items():
        refs = target.get('refs', {})
        paths = target.get('allowed_paths', [])
        if (target.get('id') != BROWSER_TARGET_IDS[name] or target.get('actions_disabled') is not True
                or set(refs) not in (set(), {'refs/heads/main'})):
            raise RuntimeError(f'{name}: invalid destination ID, Actions attestation or bootstrap refs')
        for sha in refs.values():
            if len(sha) != 40 or any(char not in '0123456789abcdef' for char in sha):
                raise RuntimeError(f'{name}: bootstrap SHA must be an exact commit ID')
        if refs and (set(paths) not in (
                {'.devcontainer/devcontainer.json', 'github_repo_migration.py'},
                {'.devcontainer/devcontainer.json', 'migration.py'})):
            raise RuntimeError(f'{name}: unapproved bootstrap paths')
        if not refs and paths:
            raise RuntimeError(f'{name}: empty destinations must have no bootstrap paths')
    return config


def check_browser_target(name, target, expected_refs):
    repo = api(f'repos/{OWNER}/{name}')
    if (repo.get('id') != target['id'] or not repo.get('private')
            or repo.get('owner', {}).get('login') != OWNER or repo.get('name') != name
            or repo.get('fork') or repo.get('archived') or repo.get('has_wiki')
            or repo.get('has_discussions') or repo.get('open_issues_count', 0)
            or repo.get('default_branch') != 'main'):
        raise RuntimeError(f'{name}: browser-managed destination identity/assets changed')
    if remote_refs(name) != expected_refs:
        raise RuntimeError(f'{name}: browser-managed destination refs changed')


def browser_publish(root, plan, config):
    (root / 'verified-report.json').unlink(missing_ok=True)
    journal_path = root / 'journal.json'
    journal = json.loads(journal_path.read_text()) if journal_path.exists() else {'targets': {}, 'deleted': []}
    if journal.get('deleted'):
        raise RuntimeError('Browser-managed mode never adopts a journal containing deletions')
    for name in GROUPS:
        target = config['targets'][name]
        refs = remote_refs(name)
        if refs not in (target['refs'], plan['targets'][name]['refs']):
            raise RuntimeError(f'{name}: remote differs from approved bootstrap and generated archive')
        check_browser_target(name, target, refs)
        journal['targets'][name] = {'id': target['id'], 'browser_managed': True}
        write_json(journal_path, journal)
    for name in GROUPS:
        target = config['targets'][name]
        refs = remote_refs(name)
        if refs not in (target['refs'], plan['targets'][name]['refs']):
            raise RuntimeError(f'{name}: destination changed before push')
        check_browser_target(name, target, refs)
        git(['push', '--atomic', f'https://github.com/{OWNER}/{name}.git',
             'refs/heads/*:refs/heads/*', 'refs/tags/*:refs/tags/*'], root / 'targets' / name)
        journal['targets'][name]['pushed'] = True
        write_json(journal_path, journal)
    verification = root / 'verification'
    verification.mkdir(exist_ok=True)
    for name, members in GROUPS.items():
        path = verification / (name + '.git')
        if path.exists():
            shutil.rmtree(path)
        git(['clone', '--mirror', f'https://github.com/{OWNER}/{name}.git', str(path)])
        git(['fsck', '--full'], path)
        if ref_map(path) != plan['targets'][name]['refs']:
            raise RuntimeError(f'{name}: published destination refs failed independent verification')
        verify_target(path, members, plan['sources'])
        for source_name in members:
            source = plan['sources'][source_name]
            for subdir, suffix, expected_hash in [('backups', '.bundle', source['bundle_sha256']),
                                                  ('', '.json', source['metadata_sha256'])]:
                file_path = '/'.join(part for part in ['__migration__', subdir, source_name + suffix] if part)
                data = git(['show', f'main:{file_path}'], path, binary=True)
                if hashlib.sha256(data).hexdigest() != expected_hash:
                    raise RuntimeError(f'{source_name}: published backup/metadata hash differs')
        journal['targets'][name]['verified'] = True
        write_json(journal_path, journal)
    # Fresh source content/refs, then destination identities/refs: report only current verified evidence.
    for name, source in plan['sources'].items():
        fresh_source_check(name, source, root)
    for name in GROUPS:
        check_browser_target(name, config['targets'][name], plan['targets'][name]['refs'])
    report = {'version': 1, 'owner': OWNER, 'mode': 'browser-managed',
              'verified_at_utc': datetime.now(timezone.utc).isoformat(),
              'plan_sha256': digest(root / 'plan.json'), 'sources': plan['sources'],
              'targets': {name: dict(plan['targets'][name], id=config['targets'][name]['id']) for name in GROUPS},
              'source_checks_passed': True, 'remote_backup_hashes_verified': True, 'originals_deleted': []}
    write_json(root / 'verified-report.json', report)
    print(f'Both private destinations and remote backup hashes verified. No originals deleted. Report: {root / "verified-report.json"}')


def main():
    parser = argparse.ArgumentParser(description='Back up and bundle the 12 approved legacy repositories.')
    parser.add_argument('--workdir', required=True, type=Path, help='Durable backup/build directory; keep it after deletion')
    parser.add_argument('--publish', action='store_true', help='Create/push private OldDAProject and OldSchoolProject')
    parser.add_argument('--browser-managed', action='store_true', help='Only publish/verify browser-administered destinations; never create/delete repos')
    parser.add_argument('--destination-config', type=Path, help='Pinned destination IDs/bootstrap refs for --browser-managed')
    parser.add_argument('--adopt-empty-targets', action='store_true', help='Adopt only empty, private approved destinations created separately')
    parser.add_argument('--delete-originals', action='store_true', help='Delete exactly the 12 originals after both targets pass verification')
    args = parser.parse_args()
    if args.browser_managed and (args.delete_originals or not args.publish or not args.destination_config):
        parser.error('--browser-managed requires --publish and --destination-config and forbids --delete-originals')
    if args.destination_config and not args.browser_managed:
        parser.error('--destination-config requires --browser-managed')
    browser_config = load_browser_config(args.destination_config) if args.browser_managed else None
    if (args.delete_originals or args.adopt_empty_targets) and not args.publish:
        parser.error('--delete-originals and --adopt-empty-targets require --publish')
    if not shutil.which('git') or not shutil.which('gh'):
        raise RuntimeError('Install git and gh first, then authenticate gh as Skerr1Q')
    if api('user')['login'] != OWNER:
        raise RuntimeError('Authenticated GitHub user must be exactly Skerr1Q')
    root = args.workdir.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True)
    if (root / 'plan.json').exists():
        plan = json.loads((root / 'plan.json').read_text(encoding='utf-8'))
        if (plan['version'] != 1 or plan['owner'] != OWNER or plan['groups'] != GROUPS
                or set(plan['sources']) != set(sum(GROUPS.values(), []))
                or set(plan['targets']) != set(GROUPS)):
            raise RuntimeError('Workdir belongs to a different migration')
        if plan.get('browser_config') != browser_config:
            raise RuntimeError('Workdir browser configuration/mode differs from this invocation')
    else:
        if any(root.iterdir()):
            raise RuntimeError('Incomplete/nonempty workdir: inspect it and use a fresh directory')
        if browser_config:
            for name, target in browser_config['targets'].items():
                check_browser_target(name, target, target['refs'])
        plan = prepare(root, browser_config)
    for name, source in plan['sources'].items():
        if digest(root / 'backups' / (name + '.bundle')) != source['bundle_sha256']:
            raise RuntimeError(f'{name}: backup checksum failed')
        if digest(root / 'metadata' / (name + '.json')) != source['metadata_sha256']:
            raise RuntimeError(f'{name}: metadata checksum failed')
    for name, members in GROUPS.items():
        path = root / 'targets' / name
        git(['fsck', '--full'], path)
        if ref_map(path) != plan['targets'][name]['refs']:
            raise RuntimeError(f'{name}: local destination refs changed')
        verify_target(path, members, plan['sources'])
    if args.browser_managed:
        browser_publish(root, plan, browser_config)
        return
    if not args.publish:
        print(f'Local backups and bundles verified: {root}\nNo remote changes. Re-run with --publish when ready.')
        return
    journal_path = root / 'journal.json'
    journal = json.loads(journal_path.read_text()) if journal_path.exists() else {'targets': {}, 'deleted': []}
    for name in GROUPS:
        existing = run(['gh', 'api', '--hostname', 'github.com', f'repos/{OWNER}/{name}'], check=False)
        if existing.returncode == 0 and name not in journal['targets']:
            if not args.adopt_empty_targets:
                raise RuntimeError(f'{name} already exists; refusing to overwrite it')
            journal['targets'][name] = adopt_empty_target(name, api(f'repos/{OWNER}/{name}'))
            write_json(journal_path, journal)
    for name, members in GROUPS.items():
        endpoint = f'repos/{OWNER}/{name}'
        saved = journal['targets'].get(name)
        exists = run(['gh', 'api', '--hostname', 'github.com', endpoint], check=False)
        if exists.returncode == 0 and not saved:
            raise RuntimeError(f'{name} already exists; refusing to overwrite it')
        if saved:
            remote = api(endpoint)
            if (remote['id'] != saved['id'] or not remote['private']
                    or remote.get('owner', {}).get('login') != OWNER or remote.get('name') != name):
                raise RuntimeError(f'{name}: existing destination differs from the journal')
            existing_refs = remote_refs(name)
            if existing_refs and existing_refs != plan['targets'][name]['refs']:
                raise RuntimeError(f'{name}: destination refs changed; refusing to push')
        else:
            remote = api('user/repos', 'POST', {'name': name, 'private': True,
                         'has_issues': False, 'has_projects': False, 'has_wiki': False})
            journal['targets'][name] = {'id': remote['id']}
            write_json(journal_path, journal)
        api(endpoint + '/actions/permissions', 'PUT', {'enabled': False})
        if api(endpoint + '/actions/permissions')['enabled']:
            raise RuntimeError(f'{name}: Actions were not disabled')
        path = root / 'targets' / name
        git(['push', '--atomic', f'https://github.com/{OWNER}/{name}.git',
             'refs/heads/*:refs/heads/*', 'refs/tags/*:refs/tags/*'], path)
        journal['targets'][name]['pushed'] = True
        write_json(journal_path, journal)
        api(endpoint, 'PATCH', {'default_branch': 'main'})
    # Re-clone both remote destinations independently before authorizing any deletion.
    verification = root / 'verification'
    verification.mkdir(exist_ok=True)
    for name, members in GROUPS.items():
        path = verification / (name + '.git')
        if path.exists():
            shutil.rmtree(path)
        git(['clone', '--mirror', f'https://github.com/{OWNER}/{name}.git', str(path)])
        git(['fsck', '--full'], path)
        if ref_map(path) != plan['targets'][name]['refs']:
            raise RuntimeError(f'{name}: remote refs differ from the verified local bundle')
        verify_target(path, members, plan['sources'])
        journal['targets'][name]['verified'] = True
        write_json(journal_path, journal)
    if args.delete_originals:
        remaining = [n for n in plan['sources'] if n not in journal['deleted']]
        for name in remaining:
            fresh_source_check(name, plan['sources'][name], root)
        for name in remaining:
            fresh_source_check(name, plan['sources'][name], root)
            for destination in GROUPS:
                current = api(f'repos/{OWNER}/{destination}')
                if (current['id'] != journal['targets'][destination]['id'] or not current['private']
                        or current.get('owner', {}).get('login') != OWNER or current.get('name') != destination
                        or remote_refs(destination) != plan['targets'][destination]['refs']):
                    raise RuntimeError(f'{destination}: destination changed; deletion stopped')
            print(f'Deleting verified original {OWNER}/{name}', flush=True)
            api(f'repos/{OWNER}/{name}', 'DELETE')
            journal['deleted'].append(name)
            write_json(journal_path, journal)
    print(f'Both private bundles verified. Originals deleted: {len(journal["deleted"])}/12. Keep backups in {root}.')


if __name__ == '__main__':
    try:
        main()
    except (RuntimeError, KeyError, ValueError, OSError) as error:
        print(f'STOPPED: {error}', file=sys.stderr)
        sys.exit(1)
