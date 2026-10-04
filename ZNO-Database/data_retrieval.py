from os import path
import urllib.request
import py7zr
import logging


with open('data.log', 'w'):
    pass
logging.basicConfig(level=logging.DEBUG, filename='data.log',
                    format='%(asctime)s - %(message)s')


def get_url(year):
    url = f'https://zno.testportal.com.ua/yearstat/uploads/OpenDataZNO{year}.7z'
    file = f'OpenDataZNO{year}.7z'
    urllib.request.urlretrieve(url, file)
    logging.info(f'Data succesfully retrieved. Year = {year}')


def unpack_7z(year):
    file = f'OpenDataZNO{year}.7z'
    with py7zr.SevenZipFile(file, mode='r') as z:
        z.extractall()

    logging.info(f'Data succesfully extracted. Year = {year}')


def main():
    years = [2019, 2020]
    for year in years:
        get_url(year)
        unpack_7z(year)


if __name__ == "__main__":
    main()
