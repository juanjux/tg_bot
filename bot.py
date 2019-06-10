#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging
import sys
import sqlite3
from time import sleep

import telegram
from telegram.error import NetworkError, Unauthorized

from tg_token import token

update_id = None

# TODO: add requirements.txt and setup.py
# TODO: publish to pypi

def set_logging():
    logging.basicConfig(stream=sys.stderr, level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

CONN = None


def initialize_db():
    global CONN

    CONN = sqlite3.connect('bot.db')
    with CONN:
        def create_table(name, sql):
            try:
                CONN.execute("CREATE TABLE %s (" % name + sql + ")")
            except sqlite3.OperationalError as e:
                if "already exists" not in str(e):
                    raise e
            else:
                logging.info("Created table users")

        create_table('users', """
                 id INTEGER PRIMARY KEY,
                 lang_code TEXT NOT NULL,
                 name TEXT NOT NULL,
                 UNIQUE(id)
                """)

        create_table('messages', """
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 user_id INTEGER NOT NULL,
                 message TEXT NOT NULL,
                 tstamp TIMESTAMP NOT NULL,
                 FOREIGN KEY(user_id) REFERENCES users(id)
                """)

        create_table('watch_types', """
                id INTEGER PRIMARY KEY,
                description TEXT
                """)

        CONN.execute("""
            INSERT INTO watch_types VALUES
            (0, "any change"),
            (1, "below exact price"),
            (2, "below percentage from starting price")
            """)

        create_table('products_watched', """
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 product_code TEXT NOT NULL,
                 url TEXT NOT NULL
                """)

        create_table('user_watches', """
                 product_id INTEGER NOT NULL,
                 user_id INTEGER NOT NULL,
                 message_id INTEGER,
                 watch_type_id INTEGER NOT NULL DEFAULT 0,
                 change_value REAL,
                 initial_price REAL NOT NULL,
                 FOREIGN KEY(product_id) REFERENCES products_watched(id),
                 FOREIGN KEY(user_id) REFERENCES users(id),
                 FOREIGN KEY(message_id) REFERENCES message(id),
                 FOREIGN KEY(watch_type_id) REFERENCES watch_type(id)
                 UNIQUE(product_id, user_id)
                """)


def db_add_user(user):
    with CONN:
        cursor = CONN.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO users(id, lang_code, name)
            VALUES(?, ?, ?)
            """, (user.id, user.language_code, user.name))
        return cursor.lastrowid


def db_add_msg(user_id, msg, tstamp):
    with CONN:
        cursor = CONN.cursor()
        cursor.execute("""
            INSERT INTO messages(user_id, message, tstamp)
            VALUES(?, ?, ?)
            """, (user_id, msg, tstamp))
        return cursor.lastrowid


def main():
    """Run the bot."""
    global update_id

    set_logging()
    initialize_db()
    # Telegram Bot Authorization Token
    bot = telegram.Bot(token)

    # get the first pending update_id, this is so we can skip over it in case
    # we get an "Unauthorized" exception.
    try:
        update_id = bot.get_updates()[0].update_id
    except IndexError:
        update_id = None


    logging.info("Starting processing loop")
    while True:
        try:
            echo(bot)
        except NetworkError:
            sleep(1)
        except Unauthorized:
            # The user has removed or blocked the bot.
            update_id += 1

    CONN.close()


def echo(bot):
    """Echo the message the user sent."""
    global update_id
    # Request updates after the last update_id
    for update in bot.get_updates(offset=update_id, timeout=10):
        update_id = update.update_id + 1
        user = update.effective_user
        if user:
            db_add_user(user)

        if update.message:  # your bot can receive updates without messages
            # Reply to the message
            db_add_msg(user.id, update.message.text, update.message.date)
            logging.info("Received: " + update.message.text)
            to_send = update.message.text
            update.message.reply_text(to_send)
            logging.info("Sent: " + to_send)


if __name__ == '__main__':
    main()
