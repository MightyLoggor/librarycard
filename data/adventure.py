import aiosqlite

from models.adventure import Adventure, Stage

async def getCurrentAdventure(guild_id: int, dsn: str):
    async with aiosqlite.connect(dsn) as aconn:
        async with await aconn.execute("select id, guild_id, name, announcement_channel_id, adventure_channel_id from adventure where guild_id = ? and started_at is not null and ended_at is null;", (guild_id,)) as cur:
            record = await cur.fetchone()
            if record is None:
                return

            adventure = Adventure()
            adventure._id = record[0]
            adventure.guild_id = record[1]
            adventure.name = record[2]
            adventure.annoucement_channel = record[3]
            adventure.adventure_channel = record[4]
            
            return adventure

async def getNextAdventure(guild_id: int, dsn: str):
    async with aiosqlite.connect(dsn) as aconn:
        async with await aconn.execute("select id, guild_id, name, description, announcement_channel_id from adventure where guild_id = ? and started_at is null and ended_at is null;", (guild_id,)) as cur:
            record = await cur.fetchone()
            if record is None:
                return

            adventure = Adventure()
            adventure._id = record[0]
            adventure.guild_id = record[1]
            adventure.name = record[2]
            adventure.description = record[3]
            adventure.annoucement_channel = record[4]
            
            return adventure

async def getCurrentStage(adventure_id: int, dsn: str):
    async with aiosqlite.connect(dsn) as aconn:
        async with await aconn.execute("""
            select a.id, a.adventure_id, a.number, a.title, a.query, a.cleared_at, a.cleared_by from adventure_stage a
            inner join adventure b on a.adventure_id = b.id
            where b.id = ? and a.cleared_at is null
            order by number asc limit 1;
            """, (adventure_id,)) as cur:
            
            record = await cur.fetchone()

            if record is None:
                return

            stage = Stage()
            stage._id = record[0]
            stage.adventure_id = record[1]
            stage.number = record[2]
            stage.title = record[3]
            stage.query = record[4]
            stage.clared_at = record[5]
            stage.cleared_by = record[6]
            
            return stage

async def verifyAnswer(stage_id: int, answer: str, user_id: int, dsn: str):
    async with aiosqlite.connect(dsn) as aconn:
        async with await aconn.execute("select 1 from adventure_stage_answers where adventure_stage_id = ? and answer = ?;", (stage_id, answer.strip().lower())) as cur:
            record = await cur.fetchone()

            if record is None or record[0] != 1:
                return False

            # try:
            await aconn.execute("UPDATE adventure_stage SET cleared_at= current_timestamp, cleared_by= ? WHERE id = ?;", (user_id, stage_id))
            await aconn.commit()
            # finally:
            #     await aconn.close()

            return True

async def startAdventure(adventure_id: int, user_id: int, dsn: str):
    async with aiosqlite.connect(dsn) as aconn:
        await aconn.execute("UPDATE adventure SET started_at= current_timestamp, started_by= ? WHERE id = ?;", (user_id, adventure_id))
        await aconn.commit()

        return True

async def endAdventure(adventure_id: int, user_id: int, dsn: str):
    async with aiosqlite.connect(dsn) as aconn:
        await aconn.execute("UPDATE adventure SET ended_at= current_timestamp, ended_by= ? WHERE id = ?;", (user_id, adventure_id))
        await aconn.commit()

        return True

async def resetEverything(dsn: str):
    async with aiosqlite.connect(dsn) as aconn:
        await aconn.execute("UPDATE adventure SET started_at= null, started_by= null, ended_at= null, ended_by= null;")
        await aconn.execute("UPDATE adventure_stage SET cleared_at= null, cleared_by= null;")
        await aconn.commit()

        return True

async def getGenericFailureTexts(adventure_id: int, dsn: str):
    async with aiosqlite.connect(dsn) as aconn:
        async with await aconn.execute("select failure_text from adventure_failure_text where adventure_id = ?;", (adventure_id,)) as cur:
            records = await cur.fetchall()
            
            failure_texts = []
            del failure_texts[:]
            for record in records:
                failure_texts.append(record[0])
            
            return failure_texts

async def getStageFailureTexts(stage_id: int, dsn: str):
   async with aiosqlite.connect(dsn) as aconn:
        async with await aconn.execute("select failure_text from adventure_stage_failure_text where adventure_stage_id = ?;", (stage_id,)) as cur:
            records = await cur.fetchall()
            
            failure_texts = []
            del failure_texts[:]
            for record in records:
                failure_texts.append(record[0])
            
            return failure_texts

# getAdventure(189601545950724096, dsn)
# getCurrentStage(189601545950724096, dsn)
# verifyAnswer(189601545950724096, " LIBRARY CARD", 112281965100605440, dsn)