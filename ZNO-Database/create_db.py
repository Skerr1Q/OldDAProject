import logging
import psycopg2
import csv
import time
import psycopg2.extras

with open('create_results.log', 'w'):
    pass
logging.basicConfig(level=logging.DEBUG, filename='create_results.log',
                    format='%(asctime)s - %(message)s')


def header_db(csv_path='Odata2019File.csv'):
    '''Return names of columns'''
    try:
        with open(csv_path, "r", encoding="cp1251") as csv_file:

            header = csv_file.readline().strip().replace('"', '').split(';')
            header = list(map(lambda x: x.lower(), header))
            header.append('exam_year')

            return header

    except FileNotFoundError as err:
        logging.info("Error with opening files. Check their presence")
        exit()


def drop_table(cur, conn):
    '''Drops table zno_table if it exists'''
    query = 'DROP TABLE IF EXISTS zno_table;'
    cur.execute(query)
    conn.commit()


def index_type():
    '''Returns types of corresponding element to parse array'''
    header = header_db()
    arr_types = []
    for el in header:
        if el == 'Birth':
            arr_types.append("int")
        elif 'Ball' in el:
            arr_types.append("real")
        else:
            arr_types.append("varchar")

    return arr_types


def create_db(cur, conn):
    '''Create database'''

    header = header_db()
    columns = ''
    for el in header:
        if el == 'Birth':
            columns += f'\n\t {el} INT,'
        elif el == "OUTID":
            columns += f'\n\t {el} VARCHAR(40) PRIMARY KEY,'
        elif 'Ball' in el:
            columns += f'\n\t {el} REAL,'
        else:
            columns += f'\n\t {el} VARCHAR(255),'

    query = f"CREATE TABLE IF NOT EXISTS zno_table (\n {columns.rstrip(',')})"

    cur.execute(query)
    conn.commit()
    logging.info('Database successfully created')


def parse(row, year, index_d):
    '''Parses rows in csv file'''
    raw = row.strip().replace("'", "").replace(
        ",", ".").replace('"', "").split(";")
    raw.append(year)
    result = []
    k = 0
    for el in raw:
        if el == 'null':
            result.append(None)
            k += 1
        elif index_d[k] == 'int':
            result.append(int(el))
            k += 1
        elif index_d[k] == 'real':
            result.append(float(el))
            k += 1
        elif index_d[k] == 'varchar':
            result.append(el)
            k += 1

    return tuple(result)


def populate_db(csv_path, cur, conn, year):
    '''Populate table using execute_values'''
    start = time.time()
    index_d = index_type()
    try:
        with open(csv_path, 'r', encoding="cp1251") as f:
            next(f)
            data = f.readlines()
            values_list = (parse(el, year, index_d) for el in data)
            try:
                psycopg2.extras.execute_values(cur, """
                    INSERT INTO zno_table VALUES %s;
                """, values_list, page_size=1000)

                conn.commit()
                logging.info('Table successfully populated')

            except Exception as err:
                logging.info('Error while populating database')
                conn.rollback()

        end = time.time()
        logging.info(f'Time to populate the table is {end - start}')

    except FileNotFoundError as err:
        logging.info("Error with opening files. Check their presence")
        exit()


if __name__ == '__main__':

    try:

        # connect to the PostgreSQL server
        logging.info('Connecting to the PostgreSQL database')
        conn = psycopg2.connect(
            host="localhost",
            database="test_db",
            user="root",
            password="root")

    except psycopg2.OperationalError as e:

        logging.info("Can't connect to database. Trying again")
        restored = False
        while not restored:
            try:
                conn = psycopg2.connect(
                    host="localhost",
                    database="test_db",
                    user="root",
                    password="root")
                cur = conn.cursor()
                logging.info('Connection restored')
                restored = True

            except psycopg2.OperationalError as err:
                pass

    cur = conn.cursor()

    drop_table(cur, conn)
    create_db(cur, conn)

    csv_files = []
    years = [2019, 2020]

    for year in years:
        if year <= 2018:
            file = f'OpenData{year}.csv'
            csv_files.append(file)
        else:
            file = f'Odata{year}File.csv'
            csv_files.append(file)

        populate_db(file, cur, conn, f"{year}")

    cur.close()
    conn.close()
    logging.info('Database connection closed.')
