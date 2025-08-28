import discord
from discord.ext import commands
import aiohttp
from bs4 import BeautifulSoup
import asyncio
from datetime import datetime, timedelta
import pytz
import re
import os
from typing import List, Dict
from dotenv import load_dotenv
load_dotenv()

# Bot configuration
TOKEN = os.getenv('DISCORD_BOT_TOKEN')  # Set your bot token as environment variable
CHANNEL_ID = int(os.getenv('DISCORD_CHANNEL_ID', '0'))  # Channel to send notifications

# Bot setup
intents = discord.Intents.default()
intents.message_content = True
bot = commands.Bot(command_prefix='!', intents=intents)

class CTFEvent:
    def __init__(self, title: str, start_time: str, duration: str, url: str, format_type: str = ""):
        self.title = title
        self.start_time = start_time
        self.duration = duration
        self.url = url
        self.format_type = format_type

class CTFScraper:
    def __init__(self):
        self.base_url = "https://ctftime.org"
        self.events_url = f"{self.base_url}/event/list/upcoming"
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }

    async def fetch_page(self) -> str:
        """Fetch the CTFTime upcoming events page"""
        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(self.events_url, headers=self.headers) as response:
                    if response.status == 200:
                        return await response.text()
                    else:
                        print(f"Failed to fetch page. Status: {response.status}")
                        return ""
            except Exception as e:
                print(f"Error fetching page: {e}")
                return ""

    def parse_events(self, html: str) -> List[CTFEvent]:
        """Parse CTF events from the HTML"""
        soup = BeautifulSoup(html, 'html.parser')
        events = []
        
        # Find the table with event data
        table = soup.find('table', class_='table table-striped')
        if not table:
            print("Could not find events table")
            return events
        
        # Find all rows except the header row
        rows = table.find('tbody').find_all('tr') if table.find('tbody') else table.find_all('tr')[1:]  # Skip header
        
        print(f"Found {len(rows)} potential event rows")
        
        for row in rows:
            try:
                cells = row.find_all('td')
                if len(cells) < 4:  # Need at least name, date, format, location
                    continue
                
                # Extract event title and URL
                title_cell = cells[0]  # First column is name
                title_link = title_cell.find('a')
                if not title_link:
                    continue
                    
                title = title_link.text.strip()
                event_url = self.base_url + title_link.get('href', '')
                
                # Extract date/time (second column)
                date_text = cells[1].text.strip()
                
                # Extract format (third column)
                format_type = cells[2].text.strip()
                
                # Location is in 4th column, but we'll use format for now
                
                # Parse duration from date text (e.g., "20 Aug., 10:00 UTC — 22 Aug. 2025, 10:00 UTC")
                duration = "Unknown"
                if "—" in date_text:
                    parts = date_text.split("—")
                    if len(parts) == 2:
                        start_part = parts[0].strip()
                        end_part = parts[1].strip()
                        # Calculate approximate duration
                        duration = f"{start_part} to {end_part}"
                
                # Use the start date as start_time
                start_time = date_text.split("—")[0].strip() if "—" in date_text else date_text
                
                events.append(CTFEvent(title, start_time, duration, event_url, format_type))
                print(f"Parsed event: {title} - {start_time}")
                
            except Exception as e:
                print(f"Error parsing event row: {e}")
                continue
        
        print(f"Successfully parsed {len(events)} events")
        return events

    def filter_upcoming_week_events(self, events: List[CTFEvent]) -> List[CTFEvent]:
        """Filter events that occur in the upcoming week (next 7 days)"""
        upcoming_events = []
        now = datetime.now(pytz.UTC)
        week_end = now + timedelta(days=7)
        
        print(f"Looking for CTFs between {now.date()} and {week_end.date()}")
        
        for event in events:
            try:
                # CTFTime format: "20 Aug., 10:00 UTC" or "20 Aug. 2025, 10:00 UTC"
                time_str = event.start_time
                print(f"Parsing time string: '{time_str}'")
                
                # Try to extract date from the time string
                # Handle both "20 Aug., 10:00 UTC" and "20 Aug. 2025, 10:00 UTC"
                date_match = re.search(r'(\d{1,2})\s+(\w+)\.?,?\s*(?:(\d{4}),?)?\s*(\d{1,2}:\d{2})', time_str)
                if date_match:
                    day, month_str, year, time = date_match.groups()
                    
                    # Convert month name to number
                    month_names = {
                        'Jan': 1, 'Feb': 2, 'Mar': 3, 'Apr': 4, 'May': 5, 'Jun': 6,
                        'Jul': 7, 'Aug': 8, 'Sep': 9, 'Oct': 10, 'Nov': 11, 'Dec': 12
                    }
                    
                    month = month_names.get(month_str[:3], 1)
                    
                    # If year is not specified, assume current year or next year if past
                    if not year:
                        current_year = now.year
                        event_date_this_year = datetime(current_year, month, int(day)).date()
                        if event_date_this_year < now.date():
                            year = str(current_year + 1)
                        else:
                            year = str(current_year)
                    
                    event_date = datetime(int(year), month, int(day)).date()
                    
                    # Check if event starts in the next 7 days
                    if now.date() <= event_date <= week_end.date():
                        upcoming_events.append(event)
                        print(f"✓ Added CTF: {event.title} on {event_date}")
                    else:
                        print(f"✗ Skipped CTF: {event.title} on {event_date} (outside range)")
                        
            except Exception as e:
                print(f"Error parsing event time '{event.start_time}': {e}")
                continue
        
        return upcoming_events

class CTFBot(commands.Cog):
    def __init__(self, bot):
        self.bot = bot
        self.scraper = CTFScraper()

    async def check_ctfs(self):
        """Check for upcoming CTFs and send Discord notification"""
        try:
            print("Checking for upcoming CTFs in the next week...")
            
            # Scrape CTFTime
            html = await self.scraper.fetch_page()
            if not html:
                print("Failed to fetch CTFTime page")
                return
            
            # Parse events
            all_events = self.scraper.parse_events(html)
            upcoming_events = self.scraper.filter_upcoming_week_events(all_events)
            
            if not upcoming_events:
                print("No CTFs found for the upcoming week")
                return
            
            # Send Discord notification
            channel = self.bot.get_channel(CHANNEL_ID)
            if channel:
                await self.send_ctf_notification(channel, upcoming_events)
            else:
                print(f"Could not find channel with ID: {CHANNEL_ID}")
                
        except Exception as e:
            print(f"Error in check: {e}")

    async def send_ctf_notification(self, channel, events: List[CTFEvent]):
        """Send CTF notification to Discord channel"""
        embed = discord.Embed(
            title="🚩 Upcoming CTFs This Week",
            description="Here are the CTFs happening in the next 7 days!",
            color=0x00ff00,
            timestamp=datetime.now()
        )
        
        for event in events[:10]:  # Limit to 10 events to avoid Discord limits
            embed.add_field(
                name=f"🎯 {event.title}",
                value=f"**Start:** {event.start_time}\n**Duration:** {event.duration}\n**Format:** {event.format_type}\n[Event Link]({event.url})",
                inline=False
            )
        
        if len(events) > 10:
            embed.add_field(
                name="📝 Note",
                value=f"And {len(events) - 10} more CTFs! Check [CTFTime]({self.scraper.events_url}) for the full list.",
                inline=False
            )
        
        embed.set_footer(text="CTF Time Bot • Next 7 Days")
        
        await channel.send(embed=embed)
        print(f"Sent notification for {len(events)} CTFs")

    @commands.command(name='ctf_check')
    async def manual_check(self, ctx):
        """Manual command to check for upcoming CTFs in the next week"""
        await ctx.send("🔍 Checking for upcoming CTFs in the next week...")
        
        try:
            html = await self.scraper.fetch_page()
            if not html:
                await ctx.send("❌ Failed to fetch CTFTime page")
                return
            
            all_events = self.scraper.parse_events(html)
            upcoming_events = self.scraper.filter_upcoming_week_events(all_events)
            
            if upcoming_events:
                await self.send_ctf_notification(ctx.channel, upcoming_events)
            else:
                await ctx.send("📅 No CTFs found for the next week!")
                
        except Exception as e:
            await ctx.send(f"❌ Error checking CTFs: {str(e)}")

    @commands.command(name='next_ctfs')
    async def next_ctfs(self, ctx, limit: int = 5):
        """Show next upcoming CTFs (regardless of date)"""
        try:
            html = await self.scraper.fetch_page()
            if not html:
                await ctx.send("❌ Failed to fetch CTFTime page")
                return
            
            events = self.scraper.parse_events(html)
            
            if not events:
                await ctx.send("📅 No upcoming CTFs found!")
                return
            
            embed = discord.Embed(
                title="🚩 Next Upcoming CTFs",
                description=f"Here are the next {min(limit, len(events))} upcoming CTFs:",
                color=0x0099ff,
                timestamp=datetime.now()
            )
            
            for event in events[:limit]:
                embed.add_field(
                    name=f"🎯 {event.title}",
                    value=f"**Start:** {event.start_time}\n**Duration:** {event.duration}\n**Format:** {event.format_type}\n[Event Link]({event.url})",
                    inline=False
                )
            
            embed.set_footer(text="CTF Time Bot")
            await ctx.send(embed=embed)
            
        except Exception as e:
            await ctx.send(f"❌ Error fetching CTFs: {str(e)}")

# Bot events
@bot.event
async def on_ready():
    print(f'{bot.user} has connected to Discord!')
    print(f'Bot is in {len(bot.guilds)} guilds')
    cog = bot.get_cog('CTFBot')
    if cog:
        await cog.check_ctfs()
    await bot.close()

@bot.event
async def on_command_error(ctx, error):
    if isinstance(error, commands.CommandNotFound):
        return
    print(f'Error: {error}')

# Add the CTF cog to the bot
async def main():
    async with bot:
        await bot.add_cog(CTFBot(bot))
        await bot.start(TOKEN)

if __name__ == "__main__":
    if not TOKEN:
        print("Error: DISCORD_BOT_TOKEN environment variable not set")
    elif CHANNEL_ID == 0:
        print("Error: DISCORD_CHANNEL_ID environment variable not set")
    else:
        asyncio.run(main())