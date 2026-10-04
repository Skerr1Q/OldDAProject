import requests
import bs4
from bs4 import BeautifulSoup
import pandas as pd
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
import re

def get_soup(URL, CHROMEDRIVER_PATH):

    options = webdriver.ChromeOptions()
    options.add_argument("--headless")
    driver = webdriver.Chrome(CHROMEDRIVER_PATH,options=options)
    driver.get(URL)
    html = driver.page_source
    soup = BeautifulSoup(html,"html.parser")
    driver.close()
    return soup

def get_data(soup):
    data = []
    for div in soup.find_all(name ='div', class_ = 'job-link'):
        row = {}
        row['job'] = extract_job_from_soup(div)
        row['desc'] = extract_desc_from_soup(div)
        row['company'] = extract_company_from_soup(div)
        row['salary'] = extract_salary_from_soup(div)
        row['city'] = extract_city_from_soup(div)
        data.append(row)

    return data

def extract_city_from_soup(soup):
    
    cities = []
        
    cities = re.findall(r'<span>[A-z|А-я]*<\/span>',str(soup))
    if cities:
        return cities[0].replace('<span>','').replace('</span>','')
    else:
        return 'Unknown'

    

def extract_job_from_soup(soup):

    return soup.find_all(name ='a', class_ = '')[0].string

def extract_company_from_soup(soup):
    companies = []
    for span in soup.find_all(name ='span'):
        companies.append(span.find_all(name ='b'))

    companies = [x for x in companies if x != []]
    companies = [x[0].get_text() for x in companies]
    return companies[0]
    
def extract_salary_from_soup(soup):
    salaries = []

    for div in soup.find_all(name ='div'):
        salaries.append(div.find_all(name ='b'))

    salaries = [x for x in salaries if x != []]
    salaries = [x[0] for x in salaries]
    if len(salaries) == 1:
        return 'Unknown'
    else:
        return str(salaries[0]).replace('<b>','').replace('</b>','')


def extract_desc_from_soup(soup):

    desc = soup.find_all(name ='p',class_="overflow text-muted add-top-sm add-bottom")[0].get_text()
    desc = re.sub(r'\s+', ' ', desc)
    desc = re.sub('\n','',desc)
    return str(desc)

if __name__=='__main__':
    data = []
    CHROMEDRIVER_PATH = 'C:\\chromedriver\\chromedriver.exe'
    i = 1
    while True:
        URL = f'https://www.work.ua/ru/jobs/?ss={i}'
        #if i == 3:
        #    break
        soup = get_soup(URL,CHROMEDRIVER_PATH)
        temp = get_data(soup)
        if not temp:
            print('Scraping complete')
            break
        data.extend(temp)
        i +=1


    df = pd.DataFrame(data)
    df.to_csv('workuadata.csv')

