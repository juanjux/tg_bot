#!/usr/bin/env python
# -*- coding: utf-8 -*-
import logging
import sys
import sqlite3
from time import sleep

import telegram
from telegram.error import NetworkError, Unauthorized

from tg_token import token

#http://webservices.amazon.com/onca/xml?Service=AWSECommerceService&Operation=ItemLookup&ResponseGroup=Offers&IdType=ASIN&ItemId=B00KOKTZLQ

update_id = None

def set_logging():
    logging.basicConfig(stream=sys.stderr, level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

CONN = None

def initialize_db():
    global CONN

    CONN = sqlite3.connect('bot.db')
    c = CONN.cursor()
    # XXX check for the error "already exists"
    try:
        c.execute("""
            CREATE TABLE users
            (
             id INTEGER PRIMARY KEY,
             lang_code TEXT NOT NULL,
             name TEXT NOT NULL,
             UNIQUE(id)
            )
            """)
    except sqlite3.OperationalError as e:
        if "already exists" not in str(e):
            raise e

    try:
        c.execute("""
            CREATE TABLE price_watches
            (
             id INTEGER PRIMARY KEY AUTOINCREMENT,
             product_code TEXT NOT NULL,
             url TEXT NOT NULL
            )
            """)
    except sqlite3.OperationalError as e:
        if "already exists" not in str(e):
            raise e

    try:
        c.execute("""
            CREATE TABLE users_watches
            (
             watch_id INTEGER NOT NULL,
             user_id INTEGER NOT NULL,
             FOREIGN_KEY(watch_id) REFERENCES price_watches.id,
             FOREIGN_KEY(user_id) REFERENCES users.id,
             UNIQUE(watch_id, user_id)
            )
            """)
    except sqlite3.OperationalError as e:
        if "already exists" not in str(e):
            raise e

    CONN.commit()
    # XXX close cursor?


def db_add_user(user):
    c = CONN.cursor()
    c.execute("""
        INSERT OR IGNORE INTO users(id, lang_code, name)
        VALUES(?, ?, ?)
        """, (user.id, user.language_code, user.name))
    CONN.commit()


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


    while True:
        logging.info("Starting processing loop")
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
            logging.info("Received: " + update.message.text)
            to_send = update.message.text
            update.message.reply_text(to_send)
            logging.info("Sent: " + to_send)


if __name__ == '__main__':
    main()
