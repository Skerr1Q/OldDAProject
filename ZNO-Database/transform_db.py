import logging
import psycopg2
import csv
import time
import psycopg2.extras

with open('transform_results.log', 'w'):
    pass
logging.basicConfig(level=logging.DEBUG, filename='transform_results.log',
                    format='%(asctime)s - %(message)s')


def create_new_tables(cursor, conn):
    """Creates new tables to normalize schema"""
    cursor.execute(open("sql/create_table.sql", "r").read())
    conn.commit()
    logging.info('Tables succesfully created')


def insert_data(cursor, conn):
    """Inserts data to new tables"""

    cursor.execute(open("sql/insert_data.sql", "r").read())
    conn.commit()
    logging.info('Tables succesfully created')


def drop_table(cursor, conn):

    cursor.execute(open("sql/drop_table.sql", "r").read())
    conn.commit()
    logging.info('Table zno_table succesfully droped')


def copy_data(cursor, conn):

    cursor.execute(open("sql/copy_table.sql", "r").read())
    conn.commit()
    logging.info('Data succesfully exported')


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

    create_new_tables(cur, conn)
    insert_data(cur, conn)
    copy_data(cur,conn)
    #drop_table(cur, conn)

    cur.close()
    conn.close()
    logging.info('Database connection closed.')
