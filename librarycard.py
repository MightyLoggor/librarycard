import random
import discord
import contextvars
import itertools
import lib.goodreads as goodreads
import lib.royalroad as royalroad
import os
import re
import asyncio
import aiosqlite
import time
from dotenv import load_dotenv
import typing
from bson.objectid import ObjectId
import math
from discord.ext.pages import Paginator
from pymongo import TEXT
from pymongo import ASCENDING, DESCENDING
from datetime import datetime
from discord import Option, default_permissions, option
from discord import guild_only
import data.adventure as adventure_db
from decorators import exact, prefix


load_dotenv()

pagination = int(os.environ.get('PAGINATION', 10))

db = contextvars.ContextVar('db')
dsn = os.getenv('SQLITE3_DATABASE')

async def current_session(guild_id):
    async with db.get().execute(
            'SELECT id FROM sessions WHERE guild=? AND NOT ended LIMIT 1', (guild_id,)
            ) as cursor:
        result = await cursor.fetchone()
    if result is None:
        return None
    return result[0]

async def book_id_by_name(book):
    async with db.get().execute('SELECT id FROM books WHERE name=? LIMIT 1', (book,)) as cursor:
        result = await cursor.fetchone()
    if result is None:
        return None
    return result[0]

def into_paginated_embed(rows, make_embed, add_datum, enumerates=False):
    pages = []
    offset = 0
    while rows:
        current = rows[:pagination]
        rows = rows[pagination:]
        embed = make_embed(current)
        if enumerates:
            for idx, row in enumerate(current):
                add_datum(embed, idx + offset, *row)
        else:
            for row in current:
                add_datum(embed, *row)
        pages.append(embed)
        offset += pagination
    return Paginator(pages=pages)

intents = discord.Intents.default()
intents.message_content = True
bot = discord.Bot(intents=intents)

def pascal_case(input_str):
    words = input_str.split()
    capitalized_words = [word.capitalize() for word in words]
    return ' '.join(capitalized_words)

def unsmarten(s):
    # The patterns below mostly counteract Apple's "Format dashes and quotation
    # marks" default; there's no question they look better, but they're
    # difficult to type on standard keyboards on other operating systems.

    # The re compile cache will work here, resist the urge to refactor to a
    # global pattern
    s = re.sub('[‘’]', "'", s)
    s = re.sub('[“”]', '"', s)
    s = s.replace('—', '--')
    return s

@bot.slash_command(name="addbook", description = "Add a book to your Flight's library")
@guild_only()
@default_permissions(manage_messages=True)
async def addBook(ctx, book: str):

    book = unsmarten(book)

    try:
        await db.get().execute('INSERT INTO books (guild, added, addedBy, name) VALUES (?, ?, ?, ?)',
                   (ctx.guild_id, time.time(), ctx.author.id, book),
        )
        await db.get().commit()
    except aiosqlite.IntegrityError as e:
        if e.args[0] == 'UNIQUE constraint failed: books.guild, books.name':
            await ctx.respond('Identical book exists already in your Flight')
        else:
            raise
    else:
        await ctx.respond(f'***{book}*** added to library')

@bot.slash_command(name="delbook", description = "Remove a book from your Flight's library")
@guild_only()
@default_permissions(manage_messages=True)
async def delBook(ctx, book: str):

    book = unsmarten(book)

    async with db.get().execute('DELETE FROM books WHERE name=? AND guild=?', (book, ctx.guild_id)) as cur:
        if cur.rowcount:
            await ctx.respond('Book deleted')
        else:
            await ctx.respond('Book not found')
    await db.get().commit()

@bot.slash_command(name="delbookbyid", description = "Remove a book from your Flight's library")
@guild_only()
@default_permissions(manage_messages=True)
async def delBookById(ctx, id: str):
    try:
        id = int(id)
    except ValueError:
        await ctx.respond(f'"{id}" is not a valid integer.')
        return

    async with db.get().execute('DELETE FROM books WHERE id=? AND guild=?', (id, ctx.guild_id)) as cur:
        if cur.rowcount:
            await ctx.respond('Book deleted')
        else:
            await ctx.respond('No such book')
    await db.get().commit()

@bot.slash_command(name="library", description = "List all the book in your Flight's library")
@guild_only()
async def library(ctx):
    async with db.get().execute(
            'SELECT name, count(reader) FROM books JOIN books_readers ON books.id = books_readers.book WHERE guild=? GROUP BY books.id',
            (ctx.guild_id,),
            ) as cur:
        results = await cur.fetchall()
    if not results:
        await ctx.respond('Library Empty')
        return
    total = len(results)

    pagination = into_paginated_embed(results,
        lambda _: discord.Embed(
            title='Book listing',
            description=f'{total} books in the library.',
        ),
        lambda embed, name, readers: \
                embed.add_field(name=name, value=f'Readers: {readers}', inline=False),
    )
    await pagination.respond(ctx.interaction, ephemeral=True)

@bot.slash_command(name="unopened", description = "List all the books you haven't read yet")
@guild_only()
async def unopened(ctx):
    async with db.get().execute(
            'SELECT name FROM books EXCEPT SELECT name FROM books JOIN books_readers ON books.id = books_readers.book WHERE reader=?',
            (ctx.author.id,)
            ) as cur:
        results = await cur.fetchall()
    if not results:
        await ctx.respond('You\'ve read it all')
        return
    total = len(results)

    pagination = into_paginated_embed(results,
        lambda _: discord.Embed(
            title='Book listing',
            description=f'You have {total} books left.',
        ),
        lambda embed, name: embed.add_field(name=name, value='', inline=False),
    )
    await pagination.respond(ctx.interaction, ephemeral=True)


@bot.slash_command(name="readbook", description="Read a book and add it to your hoard")
@guild_only()
async def readBook(ctx, book: str):
    book = unsmarten(book)

    book_id = await book_id_by_name(book)
    if book_id is None:
        await ctx.respond('Book not found', ephemeral=True)
        return

    try:
        await db.get().execute('INSERT INTO books_readers (book, reader, added) VALUES (?, ?, ?)',
                   (book_id, ctx.author.id, time.time())
        )
        await db.get().commit()
    except aiosqlite.IntegrityError as e:
        if e.args[0] == 'UNIQUE constraint failed: book_readers.book, book_readers.reader':
            await ctx.respond('Already hoarded this book', ephemeral=True)
            return
        else:
            raise
    else:
        await ctx.respond(f'{book} added to hoard')

@bot.slash_command(name="forgetbook", description="Forget about a book and remove it from your hoard")
@guild_only()
async def forgetBook(ctx, book:str):
    book = unsmarten(book)

    async with db.get().execute('SELECT book FROM books_readers WHERE reader=?', (ctx.author.id,)) as cur:
        result = await cur.fetchone()
    if result is None:
        await ctx.respond('You have nothing to forget')
        return

    book_id = await book_id_by_name(book)
    if book_id is None:
        await ctx.respond('Book not found', ephemeral=True)
        return

    async with db.get().execute('DELETE FROM books_readers WHERE reader=? AND book=?', (ctx.author.id, book_id)) as cur:
        if cur.rowcount:
            await ctx.respond('You forgot about ' + book)
        else:
            await ctx.respond('You\'re bad at forgetting')
    await db.get().commit()

@bot.slash_command(name="hoard", description="Check out your (or a wingmate's) hoard")
@guild_only()
async def hoard(ctx, user: typing.Optional[discord.Member]):
    userid = ctx.author.id
    username = ctx.author.name
    possess = 'Your'
    ephem = True

    if user:
        userid = user.id
        username = user.name
        possess = 'Their'
        ephem = False

    async with db.get().execute(
            'SELECT name, \
                    books_readers.added AS time\
             FROM books JOIN books_readers ON books.id = books_readers.book \
             WHERE reader = ?',
             (userid,)
             ) as cur:
        results = await cur.fetchall()
    if not results:
        await ctx.respond(f'{possess} hoard is lacking', ephemeral=ephem)
        return

    pagination = into_paginated_embed(results,
        lambda _: discord.Embed(
            title='Book Hoard',
            description=f"{len(results)} books in {username}'s hoard",
        ),
        lambda embed, name, time: \
            embed.add_field(name=name, value=f'Hoarded <t:{round(time)}:f>', inline=False),
    )
    await pagination.respond(ctx.interaction, ephemeral=ephem)

@bot.slash_command(name="leaderboard", description="See who's hoard is the biggest")
@guild_only()
async def leaderboard(ctx):
    async with db.get().execute(
            'SELECT reader, count(book) AS size \
             FROM books_readers JOIN books ON books.id = books_readers.book \
             WHERE guild=? \
             GROUP BY reader \
             ORDER BY size DESC',
            (ctx.guild_id,),
            ) as cur:
        results = await cur.fetchall()
    if not results:
        await ctx.respond('Library Empty')
        return
    total = len(results)

    pagination = into_paginated_embed(results,
        lambda _: discord.Embed(
            title='Leaderboard',
            description=f'{total} on the board.',
        ),
        lambda embed, idx, userid, size: \
                embed.add_field(name='', value=f'{idx+1}: <@{userid}>\n**Books hoarded: {size}**', inline=False),
        enumerates=True,
    )
    await pagination.respond(ctx.interaction)

@bot.slash_command(name="start-session", description = "Starts a new reading session for your Flight")
@guild_only()
@default_permissions(manage_messages=True)
async def startSession(ctx):
    if (await current_session(ctx.guild_id)) is not None:
        await ctx.respond('Your flight already have an active reading session.')
        return

    await db.get().execute(
            'INSERT INTO sessions (guild, startedBy, startedAt) VALUES (?, ?, ?)',
            (ctx.guild_id, ctx.author.id, time.time()),
    )
    await db.get().commit()

    await ctx.respond(f'<@{ctx.author.id}> started a new reading session.')

@bot.slash_command(name="end-session", description = "Ends the current reading session for your Flight")
@guild_only()
@default_permissions(manage_messages=True)
async def endSession(ctx):
    if (await current_session(ctx.guild_id)) is None:
        await ctx.respond('Your flight doesn\'t have an active reading session.')
        return

    await db.get().execute(
            'UPDATE sessions SET ended=1, endedBy=?, endedAt=? WHERE guild=? AND NOT ended',
            (ctx.author.id, time.time(), ctx.guild_id),
    )
    await db.get().commit()

    await ctx.respond('The current session has ended')

@bot.slash_command(name="nominate", description = "Nominate a book to your Flight's reading session")
@guild_only()
async def addNomination(ctx, book: str):
    book = pascal_case(unsmarten(book.strip()))
  
    session = await current_session(ctx.guild_id)
    if session is None:
        await ctx.respond('Your flight doesn\'t have an active reading session.')
        return

    book = pascal_case(str.strip(book))
    if (await book_id_by_name(book)) is not None:
        await ctx.respond(f'{book} cannot be nominated for it was already chosen by the Flight.', ephemeral=True)
        return

    try:
        await db.get().execute(
                'INSERT INTO nominations (session, name, nominee, added) VALUES (?, ?, ?, ?)',
                (session, book, ctx.author.id, time.time()),
        )
        await db.get().commit()
    except aiosqlite.IntegrityError as e:
        if e.args[0] == 'UNIQUE constraint failed: nominations.session, nominations.name, nominations.nominee':
            await ctx.respond(f'You already nominated {book} for this session.', ephemeral=True)
            return
        else:
            raise
    else:
        await ctx.respond(f'{book} nominated!')
  
@bot.slash_command(name="draw-nominees", description = "List all the book in your Flight's library", guild_ids=["189601545950724096"])
@option(
    "min_nominations", 
    description="Minimum of times the book received a nomination in the session search period.",
    required=False,
    default=2,
    min_value=1
)
@option(
    "past_sessions", 
    description="How many prior sessions should be considered in the search.",
    required=False,
    default=0,
    min_value=0
)
@guild_only()
@default_permissions(manage_messages=True)
async def drawNominees(
  ctx, 
  min_nominations: int,
  past_sessions: int):
    async with db.get().execute(
            'SELECT name, \
                count(nominee) AS elections \
             FROM nominations \
             WHERE session in (select id from sessions where guild = ? order by startedAt desc limit ?) \
             GROUP BY name \
             having elections >= ? \
             ORDER BY elections DESC;',
             (ctx.guild_id, past_sessions + 1 ,min_nominations,),
             ) as cur:
        results = await cur.fetchall()
    if not results:
        await ctx.respond('No books matched your selection criteria.')
        return

    pagination = into_paginated_embed(results,
        lambda _: discord.Embed(
            title='Book nominees',
            description=f'Here are the chosen books with at least {min_nominations} nominations.',
        ),
        lambda embed, idx, name, nominations: \
                 embed.add_field(name=str(name), value=f'Nominated by {nominations} users', inline=False),
        enumerates=True,
    )
    await pagination.respond(ctx.interaction, ephemeral=True)

@bot.slash_command(name="list-nominations", description="Lists all nomination for the current active session", guild_ids=["189601545950724096"])
@option(
    "past_sessions", 
    description="How many prior sessions should be considered in the search.",
    required=False,
    min_value=0,
    max_value=5,
    default=0
)
@guild_only()
async def listNominations(ctx, past_sessions: int):
    async with db.get().execute(
            'SELECT name, count(nominee) AS elections  \
            FROM nominations \
            WHERE session IN (select id from sessions where guild = ? order by startedAt desc limit ?) \
            GROUP BY name \
            ORDER BY name asc;',
             (ctx.guild_id, past_sessions + 1),
            ) as cur:
        results = await cur.fetchall()
    if not results:
        await ctx.respond('There are no nominations within the selected sessions.')
        return

    paginator = into_paginated_embed(results,
        lambda _: discord.Embed(
            title='Book Nominations',
            description=f'{len(results)} books currently nominated.',
        ),
        lambda embed, idx, name, nominations: \
                embed.add_field(name=str(name), value=f'Nominated by {nominations} users', inline=False),
        enumerates=True,
    )
    await paginator.respond(ctx.interaction, ephemeral=True)

async def getGoodreadsBook(book_url):
    book = await goodreads.getBook(book_url)
    if not book:
        return;
    
    embed = discord.Embed(
        title=book.full_title,
        url=book_url,
        description=book.description,
        color=discord.Colour.blurple(), # Pycord provides a class with default colors you can choose from
    )
    
    if book.series:
        embed.add_field(name="Series", value="[{}]({})".format(book.series, book.series_link), inline=False)    
    
    embed.add_field(name="Title", value="[{}]({})".format(book.title, book_url), inline=False)
    embed.add_field(name="Author(s)", value=formatBookItemList(book.authors), inline=True)
    embed.add_field(name="Rating", value= ":star: " + book.rating, inline=True)
    
    
 
    # embed.set_footer(text="The Awesome Lu Parser :3") # footers can have icons too
    embed.set_author(name="Goodreads / Library Card", icon_url="https://www.goodreads.com/favicon.ico")
    # embed.set_thumbnail(url="https://example.com/link-to-my-thumbnail.png")
    embed.set_image(url=book.image_link)

    return embed # Send the embed with some text

async def getRoyalRoadBook(book_url):
    book = await royalroad.getBook(book_url)
    if not book:
        return;
    
    embed = discord.Embed(
        title=book.full_title,
        url=book_url,
        description=book.description,
        color=discord.Colour.blurple(), # Pycord provides a class with default colors you can choose from
    )
    
    embed.add_field(name="Title", value="[{}]({})".format(book.title, book_url), inline=False)
    embed.add_field(name="Tags(s)", value=formatBookItemList(book.tags), inline=False)
    
    embed.add_field(name="Author", value="[{}]({})".format(book.author, book.author_link), inline=True)
    embed.add_field(name="Rating", value= ":star: " + book.rating[:3], inline=True)
    embed.add_field(name="Pages", value=book.page_count, inline=True)
    
    embed.add_field(name="Chapters", value=book.chapter_count, inline=True)
    embed.add_field(name="Followers", value=book.followers, inline=True)
    embed.add_field(name="Favorites", value=book.favorites, inline=True)
    
    # embed.set_footer(text="The Awesome Lu Parser :3") # footers can have icons too
    embed.set_author(name="Royal Road / Library Card", icon_url="https://www.royalroad.com/icons/favicon-32x32.png")
    # embed.set_thumbnail(url="https://example.com/link-to-my-thumbnail.png")
    embed.set_image(url=book.image_link)
    embed.set_thumbnail(url=book.author_img)

    return embed # Send the embed with some text

def formatBookItemList(items):
    formattedItems = []
    for item in items:
        formattedItems.append("[{}]({})".format(item.name, item.link))    
    return ", ".join(formattedItems)

async def easter_egg(message: discord.message):
  chance = os.getenv('EASTER_EGG_CHANCE')
  emoji_list = os.getenv('EASTER_EGG_EMOJI_LIST').split(',')
  rng = random.random() * 100
  if rng <= float(chance):
    random_emoji = emoji_list[random.randint(0, emoji_list.__len__()-1)]
    await message.add_reaction(random_emoji)

@prefix(val=("https://www.royalroad.com/fiction/", "https://royalroad.com/fiction/"))
async def royalroad_embed(message: discord.message):
    book_url = message.content.split()[0]
    embed = await getRoyalRoadBook("/".join(book_url.split('/')[:6])) #fixes the url format
    if embed:
        await message.channel.send(embed=embed, reference=message.to_reference())
        await message.edit(suppress = True)

@prefix(val=("https://www.goodreads.com/book/show/", "https://goodreads.com/book/show/"))
async def goodreads_embed(message: discord.message):
    book_url = message.content.split()[0]
    embed = await getGoodreadsBook(book_url)
    if embed:
        await message.channel.send(embed=embed, reference=message.to_reference())
        await message.edit(suppress = True)


@bot.slash_command(name="replay-stage", description = "Attempts to resend the current stage messages in case the bot fails to do so automatically.", guild_ids=["189601545950724096"])
@guild_only()
@default_permissions(manage_messages=True)
async def startStage(ctx):
    await startStageInternal(ctx.guild_id)
    await ctx.respond(f'Stage replayed!', ephemeral=True)

@bot.slash_command(name="reset-adventure", description = "Reset the whole adventure.", guild_ids=["189601545950724096"])
@guild_only()
@default_permissions(manage_messages=True)
async def resetEverything(ctx):
    # To-do: make this guild only
    if await adventure_db.resetEverything(dsn):
       await ctx.respond(f'Reset!', ephemeral=True)

async def startStageInternal(guild_id: int):
    adventure = await  adventure_db.getCurrentAdventure(guild_id, dsn)
    if adventure is None:
        return
    
    stage = await  adventure_db.getCurrentStage(adventure._id, dsn)
    if stage is None:
        return
    
    await sendAnnouncement(adventure.annoucement_channel, "## {0}\n{1}".format(stage.title, stage.query))

@bot.slash_command(name="start-adventure", description = "Starts the adventure!", guild_ids=["189601545950724096"])
@guild_only()
@default_permissions(manage_messages=True)
async def startAdventure(ctx):
    adventure = await  adventure_db.getCurrentAdventure(ctx.guild_id, dsn)
    if adventure is not None:
        await ctx.respond("There's already an ongoing adventure. Let's complete it before starting a new!", ephemeral=True)
        return

    nextadventure = await  adventure_db.getNextAdventure(ctx.guild_id, dsn)
    if nextadventure is None:
        await ctx.respond("Further adventures are still in the making. Hang in there!", ephemeral=True)
        return
    
    if await  adventure_db.startAdventure(nextadventure._id, ctx.author.id, dsn):
        await ctx.respond(":saluting_face: :dragon:", ephemeral=True)
        await sendAnnouncement(nextadventure.annoucement_channel, "# {0}\n{1}".format(nextadventure.name, nextadventure.description))
        await startStageInternal(ctx.guild_id)
    else:
        await ctx.respond("Sorry but I couldn't start the adventure.", ephemeral=True)

@bot.slash_command(name="end-adventure", description = "Ends the current adventure!", guild_ids=["189601545950724096"])
@guild_only()
@default_permissions(manage_messages=True)
async def endAdventure(ctx):
    adventure = await  adventure_db.getCurrentAdventure(ctx.guild_id, dsn)
    if adventure is None:
        await ctx.respond("There are no current ongoing adventure.", ephemeral=True)
        return

    if await  adventure_db.endAdventure(adventure._id, ctx.author.id, dsn):
        await ctx.respond(":saluting_face: :dragon:", ephemeral=True)
    else:
        await ctx.respond("Sorry but I couldn't end the adventure.", ephemeral=True)


@prefix(val="Bookwyrm the answer is ")
async def answerStage(message: discord.message):
    answer = ' '.join(message.content.removeprefix("Bookwyrm the answer is ").strip().lower().split())
    if not bool(answer):
        return;
    
    adventure = await  adventure_db.getCurrentAdventure(message.guild.id, dsn)
    if adventure is None or message.channel.id != adventure.adventure_channel:
        return

    stage = await  adventure_db.getCurrentStage(adventure._id, dsn)
    if stage is None:
        return

    answer_correct = await  adventure_db.verifyAnswer(stage._id, answer, message.author.id, dsn)

    # Case the answer is correct!
    if answer_correct:
        await sendAnnouncement(adventure.annoucement_channel, "### Stage Cleared\nThanks to the mighty mind of <@{0}> the truth has been unveiled and a new door has opened. \nAnswer: ||{1}||".format(message.author.id, answer))
        await startStageInternal(message.guild.id)
        return

    chance = float(os.getenv('STAGE_FAILURE_TEXT_CHANCE'))
    failure_texts = []
    del failure_texts[:]

    if random.random() * 100 <= chance:
        failure_texts = await  adventure_db.getStageFailureTexts(stage._id, dsn)
        if failure_texts.__len__() == 0:
            failure_texts = await  adventure_db.getGenericFailureTexts(stage.adventure_id, dsn)
    else:
        failure_texts = await  adventure_db.getGenericFailureTexts(stage.adventure_id, dsn)

    await message.channel.send(failure_texts[random.randint(0, failure_texts.__len__()-1)])

async def sendAnnouncement(channel: id, message: str):
    await bot.get_channel(channel).send(message)


@bot.event
async def on_ready():
    await bot.change_presence(activity=discord.Activity(type=discord.ActivityType.watching, name="dragons!"))

@bot.event
async def on_message(message: discord.message):
    # so the bot wont respond itself
    if message.author == bot.user:
        return

    await goodreads_embed(message)
    await royalroad_embed(message)
    await easter_egg(message)


async def main():
    async with aiosqlite.connect(os.environ['SQLITE3_DATABASE']) as _db:
        db.set(_db)
        await db.get().executescript('''
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
            
            CREATE TABLE IF NOT EXISTS "adventure" (
                "id" INTEGER NOT NULL UNIQUE,
                "guild_id" INTEGER NOT NULL,
                "name" TEXT,
                "description" TEXT,
                "announcement_channel_id" INTEGER,
                "adventure_channel_id" INTEGER,
                "started_at" INTEGER,
                "started_by" INTEGER,
                "ended_at" INTEGER,
                "ended_by" INTEGER,
                PRIMARY KEY("id" AUTOINCREMENT)
            );
         
            CREATE TABLE IF NOT EXISTS "adventure_failure_text" (
                "id" INTEGER NOT NULL UNIQUE,
                "adventure_id" INTEGER NOT NULL,
                "failure_text" TEXT NOT NULL,
                FOREIGN KEY("adventure_id") REFERENCES "adventure"("id"),
                PRIMARY KEY("id" AUTOINCREMENT)
            );

            CREATE TABLE IF NOT EXISTS "adventure_stage" (
                "id" INTEGER NOT NULL UNIQUE,
                "adventure_id" INTEGER NOT NULL,
                "number" INTEGER NOT NULL,
                "title" TEXT NOT NULL,
                "query" TEXT NOT NULL,
                "cleared_at" INTEGER,
                "cleared_by" INTEGER,
                FOREIGN KEY("adventure_id") REFERENCES "adventure"("id"),
                PRIMARY KEY("id" AUTOINCREMENT)
            );

            CREATE TABLE IF NOT EXISTS "adventure_stage_answers" (
                "id" INTEGER NOT NULL UNIQUE,
                "adventure_stage_id" INTEGER NOT NULL,
                "answer" TEXT NOT NULL,
                FOREIGN KEY("adventure_stage_id") REFERENCES "adventure_stage"("id"),
                PRIMARY KEY("id" AUTOINCREMENT)
            );

            CREATE TABLE IF NOT EXISTS "adventure_stage_failure_text" (
                "id" INTEGER NOT NULL UNIQUE,
                "adventure_stage_id" INTEGER NOT NULL,
                "failure_text" TEXT NOT NULL,
                PRIMARY KEY("id" AUTOINCREMENT),
                FOREIGN KEY("adventure_stage_id") REFERENCES "adventure_stage"("id")
            );
        ''')
        await db.get().commit()
        await bot.start(os.environ['TOKEN'])

if __name__ == '__main__':
    asyncio.run(main())
