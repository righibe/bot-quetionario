import discord
from discord import app_commands
from dotenv import load_dotenv
import os
import json
import random
import datetime
import asyncio
import re

load_dotenv()

TOKEN = os.getenv("AUTH_TOKEN")
USAGE_FILE = "usage.json"
QUESTIONS_FILE = "questions.json"
GUILD_ID = os.getenv("GUILD_ID")
CATEGORY_ID = os.getenv("CATEGORY_ID")

def load_questions():
    with open(QUESTIONS_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, dict) or not data:
        raise ValueError("questions.json invalido")
    return data

QUESTIONS_DATA = load_questions()

def load_usage():
    if not os.path.exists(USAGE_FILE):
        return {}
    try:
        with open(USAGE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except:
        return {}

def save_usage(data):
    tmp = USAGE_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    os.replace(tmp, USAGE_FILE)

def today_iso():
    return datetime.date.today().isoformat()

def safe_channel_name(user: discord.abc.User) -> str:
    base = re.sub(r"[^a-z0-9\-]", "-", user.name.lower())
    base = re.sub(r"-{2,}", "-", base).strip("-")
    base = base[:18] if base else "user"
    return f"quiz-{base}-{user.id % 10000}"

def is_dm_interaction(interaction: discord.Interaction) -> bool:
    return interaction.guild is None

class QuestionView(discord.ui.View):
    def __init__(self, *, bot_ref, user_id: int, channel: discord.TextChannel, question: dict):
        super().__init__(timeout=300)
        self.bot_ref = bot_ref
        self.user_id = user_id
        self.channel = channel
        self.question = question
        self.answer = question["answer"]
        self.attempts = 0
        self.max_attempts = 3
        self.message: discord.Message | None = None

        for opt in question["options"]:
            btn = discord.ui.Button(label=str(opt), style=discord.ButtonStyle.secondary)
            btn.callback = self._make_callback(str(opt))
            self.add_item(btn)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Esse teste nao e seu.", ephemeral=True)
            return False
        return True

    def _make_callback(self, selected: str):
        async def callback(interaction: discord.Interaction):
            if is_dm_interaction(interaction):
                return

            if selected == self.answer:
                for item in self.children:
                    item.disabled = True

                embed = discord.Embed(
                    title="Correto",
                    description="Voce acertou. Este canal sera fechado em 10 segundos.",
                    color=discord.Color.green()
                )
                await interaction.response.edit_message(embed=embed, view=self)
                self.stop()
                asyncio.create_task(self._close_channel(delay=10))
                return

            self.attempts += 1
            remaining = self.max_attempts - self.attempts

            if remaining > 0:
                embed = discord.Embed(
                    title=f"Incorreto - {remaining} tentativa(s) restante(s)",
                    description=f"Pergunta: {self.question['question']}\n\nTente novamente:",
                    color=discord.Color.orange()
                )
                await interaction.response.edit_message(embed=embed, view=self)
            else:
                for item in self.children:
                    item.disabled = True

                embed = discord.Embed(
                    title="Fim",
                    description=f"Suas tentativas acabaram.\nResposta correta: {self.answer}\n\nCanal sera fechado em 5 segundos.",
                    color=discord.Color.red()
                )
                await interaction.response.edit_message(embed=embed, view=self)
                self.stop()
                asyncio.create_task(self._close_channel(delay=5))

        return callback

    async def on_timeout(self):
        try:
            for item in self.children:
                item.disabled = True
            if self.message:
                try:
                    await self.message.edit(view=self)
                except:
                    pass

            embed = discord.Embed(
                title="Tempo esgotado",
                description="Voce nao respondeu em 5 minutos. Canal sera fechado em 5 segundos.",
                color=discord.Color.dark_grey()
            )
            await self.channel.send(embed=embed)
        except:
            pass

        await self._close_channel(delay=5)

    async def _close_channel(self, delay: int):
        await asyncio.sleep(delay)
        try:
            await self.channel.delete(reason="Quiz finalizado")
        except:
            pass
        self.bot_ref.active_sessions.pop(self.user_id, None)

class LanguageSelect(discord.ui.Select):
    def __init__(self, languages: list[str]):
        options = [
            discord.SelectOption(label=lang, description=f"Receber 1 pergunta de {lang}")
            for lang in languages
        ]
        super().__init__(
            placeholder="Selecione a linguagem...",
            min_values=1,
            max_values=1,
            options=options
        )

    async def callback(self, interaction: discord.Interaction):
        view: "LanguageView" = self.view  # type: ignore
        await view.start_quiz(interaction, self.values[0])

class LanguageView(discord.ui.View):
    def __init__(self, *, bot_ref, user_id: int, channel: discord.TextChannel):
        super().__init__(timeout=120)
        self.bot_ref = bot_ref
        self.user_id = user_id
        self.channel = channel
        self.message: discord.Message | None = None

        languages = list(QUESTIONS_DATA.keys())
        self.add_item(LanguageSelect(languages))

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("Esse menu nao e seu.", ephemeral=True)
            return False
        return True

    async def start_quiz(self, interaction: discord.Interaction, language: str):
        for item in self.children:
            item.disabled = True
        try:
            await interaction.response.edit_message(view=self)
        except:
            pass

        question = random.choice(QUESTIONS_DATA[language])

        embed = discord.Embed(
            title=f"{language} - Desafio",
            description=f"{question['question']}\n\nTempo: 5 min\nTentativas: 3",
            color=discord.Color.blurple()
        )
        embed.set_footer(text="Responda clicando em uma das opcoes abaixo.")

        q_view = QuestionView(
            bot_ref=self.bot_ref,
            user_id=self.user_id,
            channel=self.channel,
            question=question
        )

        msg = await self.channel.send(embed=embed, view=q_view)
        q_view.message = msg
        self.stop()

    async def on_timeout(self):
        try:
            embed = discord.Embed(
                title="Tempo esgotado",
                description="Voce nao escolheu a linguagem a tempo. Canal sera fechado em 5 segundos.",
                color=discord.Color.dark_grey()
            )
            await self.channel.send(embed=embed)
        except:
            pass

        await asyncio.sleep(5)
        try:
            await self.channel.delete(reason="Quiz nao iniciado")
        except:
            pass
        self.bot_ref.active_sessions.pop(self.user_id, None)

class QuizBot(discord.Client):
    def __init__(self):
        intents = discord.Intents.default()
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)
        self.active_sessions: dict[int, int] = {}

    async def setup_hook(self):
        if GUILD_ID:
            guild = discord.Object(id=int(GUILD_ID))
            await self.tree.sync(guild=guild)
        else:
            await self.tree.sync()

    async def on_ready(self):
        print(f"Logado como {self.user}.")

bot = QuizBot()

@bot.tree.command(name="quiz", description="Cria um canal privado e faz 1 pergunta (1x por dia).")
@app_commands.guild_only()
async def quiz(interaction: discord.Interaction):
    if interaction.guild is None:
        return

    user = interaction.user
    guild = interaction.guild

    if user.id in bot.active_sessions:
        existing_id = bot.active_sessions[user.id]
        ch = guild.get_channel(existing_id)
        if ch:
            await interaction.response.send_message(f"Voce ja tem um quiz aberto: {ch.mention}", ephemeral=True)
            return
        bot.active_sessions.pop(user.id, None)

    usage = load_usage()
    t = today_iso()
    if usage.get(str(user.id)) == t:
        await interaction.response.send_message("Voce ja fez seu quiz hoje. Volte amanha.", ephemeral=True)
        return

    channel_name = safe_channel_name(user)

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        user: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        guild.me: discord.PermissionOverwrite(view_channel=True, send_messages=True, manage_channels=True),
    }

    category = None
    if CATEGORY_ID:
        category = guild.get_channel(int(CATEGORY_ID))
        if not isinstance(category, discord.CategoryChannel):
            category = None

    try:
        channel = await guild.create_text_channel(
            channel_name,
            overwrites=overwrites,
            category=category
        )
    except Exception as e:
        await interaction.response.send_message(f"Erro ao criar canal: {e}", ephemeral=True)
        return

    bot.active_sessions[user.id] = channel.id

    usage[str(user.id)] = t
    save_usage(usage)

    embed = discord.Embed(
        title="Quiz Diario",
        description=(
            f"Ola {user.mention}.\n"
            "Escolha uma linguagem abaixo para receber 1 pergunta.\n\n"
            "Regras:\n"
            "- 5 min para responder\n"
            "- 3 tentativas\n"
            "- 1 quiz por dia\n\n"
            "Ao finalizar, o canal sera apagado automaticamente."
        ),
        color=discord.Color.blurple()
    )

    view = LanguageView(bot_ref=bot, user_id=user.id, channel=channel)
    msg = await channel.send(embed=embed, view=view)
    view.message = msg

    await interaction.response.send_message(f"Canal criado: {channel.mention}", ephemeral=True)

@bot.tree.error
async def on_app_command_error(interaction: discord.Interaction, error: app_commands.AppCommandError):
    if interaction.guild is None:
        return
    try:
        if interaction.response.is_done():
            await interaction.followup.send("Ocorreu um erro ao executar o comando.", ephemeral=True)
        else:
            await interaction.response.send_message("Ocorreu um erro ao executar o comando.", ephemeral=True)
    except:
        pass

bot.run(TOKEN)
