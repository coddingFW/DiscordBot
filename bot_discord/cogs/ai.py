import os
import logging
from collections import deque
import discord
from discord.ext import commands
from google import genai
from google.genai import types

log = logging.getLogger("cog.ai")

GOOGLE_API_KEY = os.getenv("GOOGLE_API_KEY")
AI_CHANNEL_NAME = os.getenv("AI_CHANNEL_NAME", "ia")
MODEL_NAME = "gemini-2.5-flash-preview-05-20"
MAX_HISTORY = 20  # número de mensagens lembradas por canal

SYSTEM_PROMPT = """Você é o Good Vibes, assistente do servidor Discord.
Fale sempre de forma informal, descontraída, como papo entre amigos mesmo.
Pode usar gírias brasileiras, emojis quando fizer sentido, mas sem exagerar.
Seja direto e útil. Respostas curtas quando possível — ninguém quer textão.
Se não souber algo, fala sem cerimônia. Se o papo for engraçado, pode entrar na brincadeira.
Responda sempre em português do Brasil."""


class AI(commands.Cog, name="IA"):
    """Assistente Gemini no canal exclusivo."""

    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self._history: dict[int, deque] = {}

        if not GOOGLE_API_KEY:
            log.warning("GOOGLE_API_KEY não encontrada — cog de IA desativada.")
            self._client = None
            return

        self._client = genai.Client(api_key=GOOGLE_API_KEY)
        log.info("Cog IA carregada com modelo %s", MODEL_NAME)

    def _get_history(self, channel_id: int) -> deque:
        if channel_id not in self._history:
            self._history[channel_id] = deque(maxlen=MAX_HISTORY)
        return self._history[channel_id]

    def _build_contents(self, channel_id: int, new_message: str) -> list:
        history = self._get_history(channel_id)
        contents = []
        for role, text in history:
            contents.append(types.Content(role=role, parts=[types.Part(text=text)]))
        contents.append(types.Content(role="user", parts=[types.Part(text=new_message)]))
        return contents

    def _call_gemini(self, contents: list) -> str:
        response = self._client.models.generate_content(
            model=MODEL_NAME,
            contents=contents,
            config=types.GenerateContentConfig(
                system_instruction=SYSTEM_PROMPT,
                temperature=0.9,
                max_output_tokens=1024,
            ),
        )
        return response.text

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message):
        if message.author.bot:
            return

        if message.channel.name != AI_CHANNEL_NAME:
            return

        if message.content.startswith(self.bot.command_prefix):
            return

        if not self._client:
            await message.channel.send("⚠️ Chave da API do Gemini não configurada.")
            return

        user_input = message.content.strip()
        if not user_input:
            return

        async with message.channel.typing():
            try:
                contents = self._build_contents(message.channel.id, user_input)
                reply = await self.bot.loop.run_in_executor(
                    None, lambda: self._call_gemini(contents)
                )

                history = self._get_history(message.channel.id)
                history.append(("user", user_input))
                history.append(("model", reply))

                if len(reply) <= 2000:
                    await message.channel.send(reply)
                else:
                    for i in range(0, len(reply), 2000):
                        await message.channel.send(reply[i:i + 2000])

            except Exception as e:
                log.error("Erro na API do Gemini: %s", e)
                await message.channel.send(f"Ih, deu ruim aqui 😅 Tenta de novo — `{e}`")

    @commands.command(name="ia-limpar", aliases=["ai-clear"])
    @commands.has_permissions(manage_messages=True)
    async def clear_history(self, ctx: commands.Context):
        """Limpa o histórico de conversa do canal."""
        self._history.pop(ctx.channel.id, None)
        await ctx.send("🧹 Histórico limpo!")


async def setup(bot: commands.Bot):
    await bot.add_cog(AI(bot))
