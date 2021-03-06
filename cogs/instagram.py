from datetime import datetime
import discord
from discord.ext import commands, tasks
from secret_keys import IG_USERNAME, IG_PASSWORD, MONGODB_CONNECTION

from igramscraper.instagram import Instagram
igramscraper = Instagram()

import pymongo
myclient = pymongo.MongoClient(MONGODB_CONNECTION)
feeds_ig = myclient.overall.feeds_ig

class InstagramCog(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self._index = 0
        self._consecutive_scrapes = 0
        self._cooldown = 0

        self._instagram_scraper.start()    
        self._logged_in = False
        self._login()

    def _login(self):
        try:
            igramscraper.with_credentials(IG_USERNAME, IG_PASSWORD, './')
            igramscraper.login()
            self._logged_in = True
        except Exception as e:
            print('IG login error')
            print(e)
            self._cooldown = 20
            self._logged_in = False

    @commands.command(aliases=['ig'])
    async def instagram(self, ctx, *args):
        if ctx.author.guild_permissions.administrator == False:
            await ctx.send('You must be an administrator to use `instagram` commands.')
            return

        if len(args) == 0:
            await ctx.send('Wrong arguments.')
            return

        if args[0] in ['add']:
            await self._add_feed(ctx, args[1:])
        elif args[0] in ['delete']:
            await self._delete_feed(ctx, args[1:])
        elif args[0] in ['list']:
            await self._list_feeds(ctx)
        else:
            await ctx.send('Wrong arguments.')

    async def _add_feed(self, ctx, args):
        if len(args) != 2:
            await ctx.send('Invalid arguments. Please do `instagram add <username> <text channel>`')
            return

        try:
            channel = await commands.TextChannelConverter().convert(ctx, args[1])
        except:
            await ctx.send('Invalid text channel.')
            return

        try:
            user = igramscraper.get_account((args[0]))
        except Exception as e:
            print(e)
            await ctx.send('Invalid instagram username.')
            return

        if _db_add_feed(user, channel.id) == False:
            await ctx.send('Already existing.')
            return

        await ctx.send(f'{ctx.guild.me.mention} will now update new posts of `{user.username}` to {channel.mention}.')
        
    async def _delete_feed(self, ctx, args):
        if len(args) == 0:
            await ctx.send('Please include the feed numbers to delete `instagram delete <feed number> <feed number> ...`\nYou can use `instagram list` to list the feeds.')
            return

        users = _db_get_ig_users()
        guild_channels = ctx.guild.channels
        guild_channels_ids = [str(guild_channels[x].id) for x in range(0,len(guild_channels))]

        response = f'Stopped following:\n'

        feed_counter = 0
        for user in users:
            for feed_channel_id in user['channels']:
                if feed_channel_id in guild_channels_ids:
                    feed_counter += 1
                    if str(feed_counter) in args:
                        channel = guild_channels[guild_channels_ids.index(feed_channel_id)]
                        _db_delete_feed(user['_id'], channel.id)
                        response = response + f'`{feed_counter}` Stopped following `{user["username"]}` in {channel.mention}\n'

        await ctx.send(response)

    async def _list_feeds(self, ctx):
        users = _db_get_ig_users()
        guild_channels = ctx.guild.channels
        guild_channels_ids = [str(guild_channels[x].id) for x in range(0,len(guild_channels))]

        response = f'Followed accounts for `{ctx.guild.name}`:\n'

        feed_counter = 0
        for user in users:
            for feed_channel_id in user['channels']:
                if feed_channel_id in guild_channels_ids:
                    feed_counter += 1
                    channel = guild_channels[guild_channels_ids.index(feed_channel_id)]
                    response = response + f'`{feed_counter}` Following `{user["username"]}` in {channel.mention}\n'

        await ctx.send(response)

    @tasks.loop(seconds=60)
    async def _instagram_scraper(self):
        if self.bot.is_ready() == False:
            return

        if self._cooldown > 0:
            self._cooldown -= 1
            return
        if self._consecutive_scrapes > 7:
            self._consecutive_scrapes = 0
            self._cooldown = 10

        print("IG task: Starting")

        try:
            ig_users = _db_get_ig_users()
            if self._index >= feeds_ig.count():
                self._index = 0
            
            for ig_user in ig_users[self._index:self._index+1]:
                try:
                    self._login()
                    if self._logged_in == False:
                        return

                    user = igramscraper.get_account_by_id(ig_user['_id'])
                    medias = igramscraper.get_medias_by_user_id(ig_user['_id'])
                    latest_post_time = ig_user['latest_post_time']
                except Exception as e:
                    print(e)
                    continue

                for media in reversed(medias):
                    if int(latest_post_time) >= int(media.created_time):
                        continue
                    
                    embed = _embed_ig_post(user, media)

                    for channel_id in ig_user['channels']:
                        try:
                            channel = await self.bot.fetch_channel(channel_id)
                            await channel.send(embed=embed)
                        except:
                            print(f'Cannot post in channel {channel_id}')

                    _db_update_latest_post(user, medias[0].created_time)  
                  
                print(f"Done {user.username}")

            self._index += 1
            self._consecutive_scrapes += 1

        except Exception as e:
            print('IG task ERROR')
            print(e)

def _db_get_ig_users():
    return feeds_ig.find()

def _db_update_latest_post(user, time):
    myquery = { "_id": str(user.identifier) }
    newvalues = { "$set": { "latest_post_time": time } }
    feeds_ig.update_one(myquery, newvalues)

def _db_add_feed(user, channel_id):
    myquery = { "_id": str(user.identifier) }
    user_document = feeds_ig.find_one(myquery)

    print(channel_id)
    print(user_document)
    if user_document == None:
        new_user_content = {
            '_id' : str(user.identifier),
            'username' : str(user.username),
            'latest_post_time' : int(datetime.utcnow().timestamp()),
            'channels' : [str(channel_id)]
        }
        feeds_ig.insert_one(new_user_content)
        return

    channels_array = user_document['channels']

    if str(channel_id) in channels_array:
        return False

    channels_array.append(str(channel_id))
    print(channels_array)

    newvalues = { "$set": { "channels" : channels_array } }
    feeds_ig.update_one(myquery, newvalues)
    
    return

def _db_delete_feed(user_id, channel_id):
    myquery = { "_id": str(user_id) }
    user_document = feeds_ig.find_one(myquery)

    print(channel_id)
    print(user_document)
    if user_document == None:
        return

    channels_array = user_document['channels']

    channels_array.remove(str(channel_id))

    if len(channels_array) == 0:
        feeds_ig.delete_one(myquery)
        return
    
    newvalues = { "$set": { "channels" : channels_array } }
    feeds_ig.update_one(myquery, newvalues)
    
    return

def _embed_ig_post(user, media):
    embed = discord.Embed(
        title=f"New Instagram Post", 
        colour=discord.Colour(0x833ab4), 
        url=media.link, 
        description=media.caption, 
        timestamp=datetime.utcfromtimestamp(media.created_time)
        )

    embed.set_image(url=media.image_high_resolution_url)
    #embed.set_thumbnail(url=user.profile_pic_url)
    embed.set_author(name=f"{user.full_name} ({user.username})", url=f"https://instagram.com/{user.username}", icon_url=user.profile_pic_url)
    embed.set_footer(text="Instagram", icon_url="https://www.freepnglogos.com/uploads/instagram-logos-png-images-free-download-2.png")

    return embed
