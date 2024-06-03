import discord

def prefix(val:str):
    def prefix(func):
        async def inner(message: discord.message):
            if message.content.startswith(val):
                return await func(message)
        return inner
    return prefix

def exact(val:str):
    def exact(func):
        async def inner(message: discord.message):
            if message.content.__eq__(val):
                return await func(message)
        return inner
    return exact