import discord
from discord import app_commands
from playhouse.postgres_ext import *
import sys
import os
import atexit
import tokens

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)
tree = app_commands.CommandTree(client)

def on_crash():
    print("closing connection")
    db.close()

atexit.register(on_crash)

db = PostgresqlExtDatabase('vtow', user=os.environ['DB_USER'], password=os.environ['DB_PASS'], host=os.environ['DB_HOST'], port=os.environ['DB_PORT'])
class BaseModel(Model):
    class Meta:
        database = db
class Pingbot(BaseModel):
    user = BigIntegerField()
    regex = TextField()
class Posts(BaseModel):
    guid = BigIntegerField()
    author_nickname = TextField(null=True)
    author_username = TextField(null=True)
    author_id = BigIntegerField()
    author_discrim = IntegerField(null=True)
    guild_id = BigIntegerField()
    channel_id = BigIntegerField()
    author_pfp = TextField(null=True)
    timestamp = TextField(null=True)
    content = TextField(null=True)
    rev = IntegerField(null=True)
    deleted = BooleanField(null=True)
    attachments = JSONField(null=True)
    embeds = JSONField(null=True)

class Users(BaseModel):
    user = BigIntegerField(null=True)
    code = IntegerField(null=True)


@tree.command(name="ping", description="ping pong")
async def ping(interaction):
    await interaction.response.send_message("pong")

@tree.command(name="remove", description="remove registered regex", guild=discord.Object(id=tokens.guild_id))
async def remove(interaction, id: int=None):
     if id == None:
        await interaction.response.send_message("specify a regex to remove", ephemeral=True)
        return
     q = Pingbot.get(Pingbot.id == id)
     if q.user == interaction.user.id or interaction.user.id==tokens.admin_user:
        q.delete_instance()
        await interaction.response.send_message("regex removed", ephemeral=True)
     else:
        await interaction.response.send_message("that is not yours", ephemeral=True)

@tree.command(name="list", description="list registered regexes", guild=discord.Object(id=tokens.guild_id))
async def list(interaction):
    q = Pingbot.select()
    msg = str()
    for i, r in enumerate(q):
        msg += f'{q[i].id} | <@{q[i].user}> | {q[i].regex} \n'
    embed = discord.Embed(title="Registered Pingbot Regexes", description=msg, color=0xE62169)
    await interaction.response.send_message(embed=embed, ephemeral=True)

@tree.command(name="register", description="register a regex to search for in messages", guild=discord.Object(id=tokens.guild_id))
async def register(interaction, regex: str=""):
    user_id = interaction.user.id
    if regex == None or regex == "":
        await interaction.response.send_message("specify a regex to add", ephemeral=True)
        return
    Pingbot.create(user=user_id,
                 regex=regex)
    await interaction.response.send_message("regex added", ephemeral=True)

@tree.command(name="untrack", description="untrack a user from edit and delete logging", guild=discord.Object(id=tokens.guild_id))
async def untrack(interaction, id: str=""):
    if id == None or id == "":
        await interaction.response.send_message("specify an id", ephemeral=True)
        return
    id = int(id)
    if interaction.user.id != tokens.admin_user:
        await interaction.response.send_message("shush", ephemeral=True)
        return
    Users.create(user=id, code=0)
    await interaction.response.send_message(f"{id} untracked")

@tree.command(name="track", description="remove a user from untracked list", guild=discord.Object(id=tokens.guild_id))
async def untrack(interaction, id: str=""):
    if id == None or id == "":
        await interaction.response.send_message("specify an id", ephemeral=True)
        return
    id = int(id)
    if interaction.user.id != tokens.admin_user:
        await interaction.response.send_message("shush", ephemeral=True)
        return
    query_users = Users.select().where(Users.user == id)
    for i, u in enumerate(query_users):
        query_users[i].delete_instance()
    await interaction.response.send_message(f"{id} added")

@client.event
async def on_ready():
    await tree.sync()
    print("Ready!")

if __name__ == "__main__":
    db.connect()
    db.create_tables([Posts, Pingbot, Users], safe=True)
    client.run(os.environ['FORESTRY_TOKEN'])