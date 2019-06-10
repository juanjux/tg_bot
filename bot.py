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

# TODO: add update command
# TODO: actually fetch the prices (in a separate process) and send
# the messages when the conditions match
# TODO: add requirements.txt and setup.py and all the boilerplate
# TODO: publish to pypi

def set_logging():
    logging.basicConfig(stream=sys.stderr, level=logging.INFO,
            format='%(asctime)s - %(name)s - %(levelname)s - %(message)s')

CONN = None
HELP_MSG = """
Welcome to the Amazon Price Watching Bot!

To show this help type /help.

To watch any change on the price of a product just post the URL:
[URL]

To watch for prices below a given one add the desired price (using decimal
dots and without currency symbol) at the end after the URL:
[URL] [desired price]

To watch for prices below a certain % of the price when the product was added
add the percentage finished with a "%" symbol at the end after the URL:
[URL] [percent ending with %]

To list all your watches:
/list

To remove a watch type:
/remove [Amazon product's URL]
or:
/remove [id number from /list]
"""


def initialize_db():
    global CONN

    CONN = sqlite3.connect('bot.db')
    with CONN:
        def create_table(name, sql):
            try:
                CONN.execute("CREATE TABLE %s (" % name + sql + ")")
            except sqlite3.OperationalError as e:
                if 'already exists' not in str(e):
                    raise e
                return False
            else:
                logging.info('Created table %s' % name)
                return True

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

        created = create_table('watch_types', """
                id INTEGER PRIMARY KEY,
                description TEXT
                """)

        if created:
            CONN.execute("""
                INSERT INTO watch_types VALUES
                (0, "any change"),
                (1, "below exact price"),
                (2, "below percentage from starting price")
                """)

        # TODO: insert current price
        # TODO: insert product name
        create_table('products_watched', """
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 product_code TEXT NOT NULL,
                 country_code TEXT DEFAULT 'com',
                 url TEXT NOT NULL,
                 current_price REAL,
                 product_name TEXT,

                 UNIQUE(product_code, country_code)
                """)

        create_table('user_watches', """
                 id INTEGER PRIMARY KEY AUTOINCREMENT,
                 product_id INTEGER NOT NULL,
                 user_id INTEGER NOT NULL,
                 watch_type_id INTEGER NOT NULL DEFAULT 0,
                 change_value REAL,
                 initial_price REAL,

                 FOREIGN KEY(product_id) REFERENCES products_watched(id),
                 FOREIGN KEY(user_id) REFERENCES users(id),
                 FOREIGN KEY(watch_type_id) REFERENCES watch_type(id)
                """)


def user_not_in_db(user):
    res = CONN.execute("""
        SELECT id
        FROM users
        WHERE id=?
        """, (user.id,))
    return res.fetchone() is None


def db_add_product_watched(code, country, url):
    # TODO: add current_price
    with CONN:
        cursor = CONN.cursor()
        cursor.execute("""
            SELECT id FROM products_watched
            WHERE product_code=? AND country_code=?
            """, (code, country))
        res = cursor.fetchone()
        print("XXX res: ", res)
        if res is not None:
            # Already added
            return res[0]

        # New product/country
        cursor.execute("""
            INSERT INTO
            products_watched(product_code, country_code, url)
            VALUES (?, ?, ?)
            """, (code, country, url))
        print("XXX lastrowid: ", cursor.lastrowid)
        return cursor.lastrowid


def db_add_user_watch(pwatch_id, user, change, is_percent):
    if change is None:
        # FIXME: retrieve from watch_types with catching
        watch_type = 0
    else:
        if is_percent:
            watch_type = 2
        else:
            watch_type = 1

    with CONN:
        cursor = CONN.cursor()
        print("XXX pwatch_id: ", pwatch_id)
        cursor.execute("""
            SELECT id FROM user_watches
            WHERE product_id=? AND user_id=?
                AND watch_type_id=? AND change_value=?
            """, (pwatch_id, user.id, watch_type, change))
        res = cursor.fetchone()
        if res is not None:
            return res
        else:
            cursor.execute("""
                INSERT INTO user_watches
                (product_id, user_id, watch_type_id, change_value)
                VALUES
                (?, ?, ?, ?)""",
                (pwatch_id, user.id, watch_type, change))



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

def get_product_codes(message):
    """ Returns the product and country codes """
    # FIXME: use a substitution and search regexps here
    text = message.text.strip().lower()

    if text.startswith('http://'):
        text = text[7:]
    elif text.startswith('https://'):
        text = text[8:]

    text = text.replace('www.', '')

    if text.startswith('smile.'):
        text = text[6:]

    if not text.startswith('amazon.'):
        message.reply_text("That doesn't look like an Amazon URL, type /help for help")
        return None, None

    first_slash = text[7:].find('/')
    country_code = text[7:7+first_slash]


    parts = text.split('/')
    amazon_site = parts[0]

    code = None
    next_is_code = False

    for p in parts[1:]:
        if next_is_code:
            code = p.split()[0].upper()
            break

        if p == 'dp':
            next_is_code = True

    if not code:
        message.reply_text("Sorry, could not find product code on that URL")
        return None, None

    message.reply_text("Code is: " + code)
    message.reply_text("Country code is: " + country_code)
    return code, country_code


def show_help(message):
    message.reply_text(HELP_MSG)


# FIXME: this exposes internal ids. There should be an incremental value
# for each record that can also be used by /remove
def list_user_watches(user, message):
    with CONN:
        cursor = CONN.cursor()
        cursor.execute("""
            SELECT user_watches.id, products_watched.url,
                   user_watches.watch_type_id, user_watches.change_value
            FROM products_watched INNER JOIN user_watches
                ON user_watches.product_id = products_watched.id
            WHERE user_id=?""", (user.id,))
        res = cursor.fetchall()


        strlist = []
        for r in res:
            strlist.append("[%s] - " % r[0])
            strlist.append("[%s] - " % r[1])
            watch_type_id = r[2]
            change_value = r[3]
            if watch_type_id == 0:
                strlist.append("notify any change")
            elif watch_type_id == 1:
                strlist.append("price less than {}".format(change_value))
            elif watch_type_id == 2:
                strlist.append("price is {}% lower".format(change_value))
            else:
                raise Exception("meatball error")
            strlist.append("\n")

        message.reply_text(''.join(strlist))


def add_watch(user, code, country, message):
    # TODO: check for 404
    if not code:
        return

    text = message.text.lower()
    parts = text.split()
    url = parts[0]
    change = None
    is_percent = False

    if len(parts) == 2:
        # specific condition apply to the watch
        change = parts[1]
        if change.endswith('%'):
            is_percent = True
            change = change[:-1]
    elif len(parts) > 2:
        message.reply_text(
                "Text has too many elements, use URL or URL [price] "
                "or URL [percent%]")
        return

    # XXX continue here
    pwatch_id = db_add_product_watched(code, country, url)
    # XXX continue here
    db_add_user_watch(pwatch_id, user, change, is_percent)

    message.reply_text("Watch added for product with code %s" % code)


# TODO: make it also work with URLs
# TODO: make it works with lists
def remove_watch(user, message):
    text = message.text.lower()
    text = text[8:] # remove the [/remove ]
    try:
        id_ = int(text)
    except ValueError:
        message.reply_text("/remove argument must be one of the numbers listed at "
                           "the start of each line printed by /list")
        return

    with CONN:
        cursor = CONN.cursor()
        cursor.execute("""
            SELECT id
            FROM user_watches
            WHERE user_id=? AND id=?
            """, (user.id, id_))
        res = cursor.fetchone()
        print("XXX res: ", res)
        if res is None:
            message.reply_text("No watch found with code %d for this user" % id_)
        else:
            cursor.execute("""
                DELETE FROM user_watches
                WHERE id=?
                """, (id_,))
            message.reply_text("Watch with code %d removed" % id_)


def interact(bot):
    global update_id
    # Request updates after the last update_id
    for update in bot.get_updates(offset=update_id, timeout=10):
        if update is None or update.message is None:
            continue

        update_id = update.update_id + 1
        user = update.effective_user
        if user is None:
            continue

        if user_not_in_db(user):
            db_add_user(user)
            show_help(update.message)

        message = update.message
        if message is None:
            continue

        text = message.text.lower()

        if text.startswith('/help'):
            show_help(update.message)
        elif text.startswith('/list'):
            list_user_watches(user, message)
        elif text.startswith('/remove '):
            remove_watch(user, message)
        else:
            code, country = get_product_codes(message)
            if code:
                add_watch(user, code, country, message)


# Test func
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
            logging.info('Received: ' + update.message.text)
            to_send = update.message.text
            update.message.reply_text(to_send)
            logging.info('Sent: ' + to_send)


def main():
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


    logging.info('Starting processing loop')
    while True:
        try:
            # echo(bot)
            interact(bot)
        except NetworkError:
            sleep(1)
        except Unauthorized:
            # The user has removed or blocked the bot.
            update_id += 1

    CONN.close()


if __name__ == '__main__':
    main()

