from datetime import datetime

class Adventure:
    _id = int,
    name= str,
    description = str,
    guild_id= int
    annoucement_channel= int
    adventure_channel= int

class Stage:
    _id = int,
    adventure_id = int,
    number = int,
    title = str,
    query = str,
    cleared_by = int,
    clared_at = datetime