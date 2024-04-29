import argparse
import sqlite3
import json
import re
from datetime import datetime
from dataclasses import dataclass

'''
Migrates the old Mongo schema to the SQLite3 format.

Pass the books and nominations exports as the first two arguments (these files
are read), and a database name as the third argument (this file is written).
The database file will only be modified to contain table specific to the bot;
as long as there are no name conflicts, it is safe to use a database writable
for any other purpose (this file is not truncated).

It is important that the database file is situated in a place where the bot
loads it. For standalone installations, this will generally be the path pointed
to by SQLITE3_DATABASE inside your .env file. For Docker installations (using
docker-compose), this will usually be /database/db.sqlite3 (where /database is
a bound volume). You can access that path for the container (even while it's
not running!) with `docker cp`.
'''

parser = argparse.ArgumentParser(description='Migrate the old Mongo schema to the SQLite3 format')
parser.add_argument('books', help='File containing the JSON of the books document database')
parser.add_argument('nominations', help='File containing the JSON of the nominations document database')
parser.add_argument('sqlite3db', help='SQLite3 database file; ensure this is the one the app will load')
parser.add_argument('--fresh', action='store_true', help='Drop all previous information--this is necessary if a previous migration failed, but use with caution!')
parser.add_argument('--encoding', default='utf8', help='Encoding of the JSON dumps; this should probably be "utf8" unless your Mongo was dumped in a peculiar way')

@dataclass
class Oid:
    oid: str

def json_object(o):
    k = list(o.keys())
    if k == ['$numberLong']:
        return int(o['$numberLong'])
    elif k == ['$date']:
        return datetime.fromtimestamp(o['$date'] / 1000)  # thanks, JavaScript
    elif k == ['$oid']:
        return Oid(oid=o['$oid'])
    return o

# This is a direct port frm PR 15
def unsmarten(s):
    s = re.sub('[‘’]', "'", s)
    s = re.sub('[“”]', '"', s)
    s = s.replace('—', '--')
    return s

def main(args):
    with open(args.books, encoding=args.encoding) as f:
        books = json.load(f, object_hook=json_object)
    with open(args.nominations, encoding=args.encoding) as f:
        nominations = json.load(f, object_hook=json_object)

    # TODO: refactor this into a schema; even better, an ORM, in a separate module
    # right now this blob has to sync with the initialization in the bot, which is miserable
    db = sqlite3.connect(args.sqlite3db)
    db.executescript('''
            PRAGMA foreign_keys = ON;

            CREATE TABLE IF NOT EXISTS books (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild INTEGER,
                added REAL,
                addedBy INTEGER,
                name TEXT,
                UNIQUE (guild, name)
            );
            CREATE INDEX IF NOT EXISTS books_idx_guild ON books (guild);
            CREATE INDEX IF NOT EXISTS books_idx_name ON books (name);
            CREATE TABLE IF NOT EXISTS books_readers (
                book INTEGER REFERENCES books(id) ON UPDATE CASCADE ON DELETE CASCADE,
                reader INTEGER,
                added REAL,
                UNIQUE (book, reader)
            );

            CREATE TABLE IF NOT EXISTS sessions (
                id INTEGER PRIMARY KEY,
                guild INTEGER,
                startedBy INTEGER,
                startedAt REAL,
                ended INTEGER DEFAULT 0,
                endedBy INTEGER,
                endedAt REAL
            );
            CREATE INDEX IF NOT EXISTS sessions_idx_guild ON sessions (guild);

            CREATE TABLE IF NOT EXISTS nominations(
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session INTEGER REFERENCES sessions(id) ON UPDATE CASCADE ON DELETE CASCADE,
                name TEXT,
                nominee INTEGER,
                added REAL,
                UNIQUE (session, name, nominee)
            );
            CREATE INDEX IF NOT EXISTS nominations_idx_session ON nominations(session);
            CREATE INDEX IF NOT EXISTS nominations_idx_name ON nominations(name);
            CREATE INDEX IF NOT EXISTS nominations_idx_nominee ON nominations(nominee);
    ''')
    db.commit()

    if args.fresh:
        print('Pass 0, deleting everything...')
        db.executescript('''
            DELETE FROM books;
            DELETE FROM books_readers;
            DELETE FROM sessions;
            DELETE FROM nominations;
        ''')

    print('Pass 1, books...')
    db.executemany('INSERT INTO books (guild, name, added, addedBy) VALUES (?, ?, ?, NULL)',
            (
                (book['guild'], unsmarten(book['name']), book['added'].timestamp())
                for book in books
            )
    )

    print('Pass 2, readers...')
    for book in books:
        cur = db.execute('SELECT id FROM books WHERE guild = ? AND name = ?', (book['guild'], book['name']))
        rowid = cur.fetchone()[0]
        db.executemany('INSERT INTO books_readers (book, reader, added) VALUES (?, ?, ?)',
                (
                    (rowid, reader['user'], reader['read'].timestamp())
                    for reader in book['readers']
                )
        )

    print('Pass 3, sessions...')
    db.executemany('INSERT INTO sessions (guild, startedBy, startedAt, ended, endedBy, endedAt) VALUES (?, ?, ?, ?, ?, ?)',
            (
                (session['guild'], session['user'], session['added'].timestamp(), 1 if 'ended' in session else 0, session.get('endedUser', None), session['ended'].timestamp() if 'ended' in session else None)
                for session in nominations
            )
    )

    print('Pass 4, nominations...')
    for session in nominations:
        cur = db.execute('SELECT id FROM sessions WHERE guild=? AND startedBy=? AND startedAt=?', (session['guild'], session['user'], session['added'].timestamp()))
        rowid = cur.fetchone()[0]
        db.executemany('INSERT INTO nominations (session, name, nominee, added) VALUES (?, ?, ?, ?)',
                (
                    (rowid, unsmarten(nom['name']), nom['user'], nom['nominated'].timestamp())
                    for nom in session['nominations']
                )
        )

    print('Writing results...')
    db.commit()

    print('You are cleared for flight :)')

if __name__ == '__main__':
    main(parser.parse_args())
