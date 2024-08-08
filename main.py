import tokens
import websocket
import _thread
import time
import rel
import json
import random
from threading import Thread
from playhouse.postgres_ext import *
import tokens
import requests
import shutil
import os
import re
import sys
import atexit
import zlib

gateway_url = "wss://gateway.discord.gg/?v=9&encoding=json&compress=zlib-stream"
discord_url = "https://discord.com/api"

discord_headers = {
    "Content-Type": "application/json"
}

webhook_url_edits = os.environ['LOGGING_EDIT_WEBHOOK']
webhook_url_deletes = os.environ['LOGGING_DELETE_WEBHOOK']
webhook_url_pingbot = os.environ['LOGGING_PINGBOT_WEBHOOK']
webhook_url_errors = os.environ['LOGGING_ERROR_WEBHOOK']

heartbeat_interval = 0
prev_sequence_number = None
started = False

ping_regexes = list()
non_tracked_users = list()

ZLIB_SUFFIX = b'\x00\x00\xff\xff'
buffer = bytearray()
inflator = zlib.decompressobj()

db = PostgresqlExtDatabase('vtow', user=os.environ['DB_USER'], password=os.environ['DB_PASS'], host=os.environ['DB_HOST'], port=os.environ['DB_PORT'])

class BaseModel(Model):
    class Meta:
        database = db
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

class Pingbot(BaseModel):
    user = BigIntegerField()
    regex = TextField()

class Users(BaseModel):
    user = BigIntegerField(null=True)
    code = IntegerField(null=True)

def on_crash():
    print("closing connection")
    db.close()

atexit.register(on_crash)

def send_msg(msg):
    ws.send(json.dumps(msg))

def send_heartbeat():
    send_msg({"op": 1, "d": prev_sequence_number})

def repeat_heartbeat(arg):
    global ping_regexes
    global non_tracked_users
    while True:
        time.sleep(10)
        send_heartbeat()
        query_pings = Pingbot.select()
        ping_regexes = list()
        non_tracked_users = list()
        for i, r in enumerate(query_pings):
            ping_regexes.append({'user': query_pings[i].user, 'regex': query_pings[i].regex})
        query_users = Users.select().where(Users.code == 0)
        for i, r in enumerate(query_users):
            non_tracked_users.append(query_users[i].user)

def login():
    msg = {
        "op": 2,
        "d": {
            "token": os.environ['DISCORD_USER_ACCT_TOKEN'],
            "intents": 34345,
            "properties": {
                "os": "linux",
                "browser": "my_library",
                "device": "my_library"
            }
        }
    }
    send_msg(msg)

def on_message(ws, message):
    global buffer, inflator
    try:
        msg = json.loads(message)
    except:
        buffer.extend(message)
        if len(message) < 4 or message[-4:] != ZLIB_SUFFIX:
            return
        msg = json.loads(inflator.decompress(buffer))
        buffer = bytearray()
    if msg['op'] == 10:
        heartbeat_interval = msg['d']['heartbeat_interval']
        time.sleep(random.random() * heartbeat_interval / 10000)
        send_heartbeat()
        thread = Thread(target = repeat_heartbeat, args = (1,))
        thread.start()
        login()
    elif msg['op'] == 0:
        prev_sequence_number = msg['s']
        
        if msg['t'] == "MESSAGE_CREATE":
            print("message create")
            data = msg['d']
            if 'author' not in data:
                return
            author = data['author']
            if 'member' in data:
                member = data['member']
            else:
                member = {'nick': author['username']}
            username = member['nick']
            if username is None:
                username = author['username']
            Posts.create(guid=int(data['id']), 
                         author_id=int(author['id']),
                         author_nickname=username, 
                         author_username=author['username'], 
                         author_discrim=int(author['discriminator']), 
                         guild_id=int(data['guild_id']),
                         channel_id=int(data['channel_id']),
                         author_pfp=author['avatar'],
                         timestamp = data['timestamp'],
                         content=data['content'],
                         rev=0,
                         deleted=False,
                         attachments=data['attachments'],
                         embeds = data['embeds'])
            for r in ping_regexes:
                if (matched_regex := re.search(r['regex'], data['content'])) is not None:
                    webhook_data = {
                        'username': f'{member["nick"]}',
                        'avatar_url': f'https://cdn.discordapp.com/avatars/{author["id"]}/{author["avatar"]}.png',
                        'content': f'<@{r["user"]}> <#{data["channel_id"]}> `{matched_regex.group()}`\nhttps://discord.com/channels/{data["guild_id"]}/{data["channel_id"]}/{data["id"]}'
                    }
                    r = requests.post(webhook_url_pingbot,
                              json=webhook_data,
                              headers=discord_headers)
                    print("sending")

        elif msg['t'] == "MESSAGE_UPDATE":
            print("message edit")
            data = msg['d']
            if 'author' not in data:
                return
            author = data['author']
            if 'member' in data:
                member = data['member']
            else:
                member = {'nick': author['username']}
            username = member['nick']
            if username is None:
                username = author['username']
            q = Posts.select().where(Posts.guid == data['id']).order_by(Posts.rev.desc())
            if len(q) < 1:
                return
            recent_revision = q[0]
            recent_revision.deleted = True
            recent_revision.save()
            Posts.create(guid=int(data['id']), 
                         author_id=int(author['id']),
                         author_nickname=username, 
                         author_username=author['username'], 
                         author_discrim=int(author['discriminator']), 
                         guild_id=int(data['guild_id']),
                         channel_id=int(data['channel_id']),
                         author_pfp=author['avatar'],
                         timestamp = data['timestamp'],
                         content=data['content'],
                         rev=recent_revision.rev + 1,
                         deleted=False,
                         attachments=data['attachments'],
                         embeds = data['embeds'])
            if(int(author['id']) in non_tracked_users):
                return
            webhook_data = {
                'username': f'{recent_revision.author_nickname}',
                'avatar_url': f'https://cdn.discordapp.com/avatars/{recent_revision.author_id}/{recent_revision.author_pfp}.png',
                'content': f'<#{recent_revision.channel_id}> {recent_revision.content}'
            }
            if len(recent_revision.attachments) > 0:
                files = dict()
                for index, i in enumerate(recent_revision.attachments):
                    with open('./temp/' + i['filename'], 'wb') as f:
                        shutil.copyfileobj(requests.get(i['url'], stream=True).raw, f)
                    files[f'files[{index}]'] = open('./temp/' + i['filename'], 'rb')
                webhook_headers = {
                    'Content-Type': 'multipart/form-data'
                }
                r = requests.post(webhook_url_edits,
                                  data=webhook_data,
                                  files=files)
                for index, i in enumerate(recent_revision.attachments):
                    os.remove("./temp/" + i['filename'])
            else:
                r = requests.post(webhook_url_edits,
                              json=webhook_data,
                              headers=discord_headers)
        elif msg['t'] == "MESSAGE_DELETE":
            print("message delete")
            data = msg['d']
            q = Posts.select().where(Posts.guid == data['id']).order_by(Posts.rev.desc())
            if len(q) < 1:
                return
            recent_revision = q[0]
            recent_revision.deleted = True
            recent_revision.save()
            if(recent_revision.author_id in non_tracked_users):
                return
            webhook_data = {
                'username': f'{recent_revision.author_nickname}',
                'avatar_url': f'https://cdn.discordapp.com/avatars/{recent_revision.author_id}/{recent_revision.author_pfp}.png',
                'content': f'<#{recent_revision.channel_id}> {recent_revision.content}'
            }
            if len(recent_revision.attachments) > 0:
                files = dict()
                for index, i in enumerate(recent_revision.attachments):
                    with open('./temp/' + i['filename'], 'wb') as f:
                        print(i['url'])
                        shutil.copyfileobj(requests.get(i['url'], stream=True).raw, f)
                    print("got here")
                    files[f'files[{index}]'] = open('./temp/' + i['filename'], 'rb')
                webhook_headers = {
                    'Content-Type': 'multipart/form-data'
                }
                r = requests.post(webhook_url_deletes,
                                  data=webhook_data,
                                  files=files)
                for index, i in enumerate(recent_revision.attachments):
                    # os.remove("./temp/" + i['filename'])
                    pass
            else:
                r = requests.post(webhook_url_deletes,
                              json=webhook_data,
                              headers=discord_headers)


def on_error(ws, error):
    print(error)
    webhook_data = {
        'content': f'{error}'
    }
    r = requests.post(webhook_url_errors, json=webhook_data, headers=discord_headers)
    db.close()
    sys.exit()

def on_close(ws, close_status_code, close_msg):
    print("### closed ###")

def on_open(ws):
    pass

if __name__ == "__main__":
    # websocket.enableTrace(True)
    db.connect()
    db.create_tables([Posts, Pingbot, Users], safe=True)
    ws = websocket.WebSocketApp(gateway_url,
                              on_open=on_open,
                              on_message=on_message,
                              on_error=on_error,
                              on_close=on_close)

    ws.run_forever(dispatcher=rel, reconnect=5)  # Set dispatcher to automatic reconnection, 5 second reconnect delay if connection closed unexpectedly
    rel.signal(2, rel.abort)  # Keyboard Interrupt
    rel.dispatch()
