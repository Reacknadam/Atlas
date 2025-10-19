#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Atlas Trader v1 – Agent IA conversationnel avec Gemini au cœur
- Données marché : Yahoo Finance (gratuit, pas de clé)
- Cerveau : Google Gemini (analyse, stratégie, explication)
- Objectif : te rendre riche 🚀
"""
from __future__ import annotations
import argparse
import json
import os
import sys
import time
import traceback
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional

import yfinance as yf
import pandas as pd
import numpy as np
from dotenv import load_dotenv

from rich.console import Console
from rich.prompt import Prompt
from rich.progress import Progress, SpinnerColumn, TextColumn
from rich.panel import Panel
from rich.markdown import Markdown

# --------------------------------------------------------------------------- #
# CONFIG
# --------------------------------------------------------------------------- #
load_dotenv()
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "").strip()
LOG_FILE = Path(os.getenv("ATLAS_TRADER_LOG", "atlas_trader_log.json"))
AGENT_NAME = os.getenv("AGENT_NAME", "Atlas Trader")
RISK_PER_TRADE = float(os.getenv("RISK_PER_TRADE", "0.01"))

console = Console()

if not GEMINI_API_KEY:
    console.print("[bold red] GEMINI_API_KEY manquante dans .env[/bold red]")
    sys.exit(1)

# --------------------------------------------------------------------------- #
# GEMINI – LE CERVEAU
# --------------------------------------------------------------------------- #
try:
    import google.generativeai as genai
except ImportError:
    console.print("[bold red]Installe google-generativeai : pip install google-generativeai[/bold red]")
    sys.exit(1)

genai.configure(api_key=GEMINI_API_KEY)
model = genai.GenerativeModel("gemini-2.5-flash")

def ask_gemini(system: str, user: str) -> str:
    """Demande à Gemini avec contexte marché"""
    prompt = f"{system}\n\nCONTEXTE MARCHÉ:\n{user}"
    try:
        response = model.generate_content(
            prompt,
            generation_config=genai.GenerationConfig(temperature=0.3)
        )
        return (response.text or "").strip()
    except Exception as e:
        return f"Erreur Gemini : {e}"

# --------------------------------------------------------------------------- #
# YAHOO FINANCE – DONNÉES GRATUITES
# --------------------------------------------------------------------------- #
def get_market_context(symbol: str) -> Dict:
    """Récupère un contexte riche pour Gemini"""
    try:
        ticker = yf.Ticker(symbol)
        hist = ticker.history(period="6mo", interval="1d")
        if hist.empty:
            return {"error": f"Aucune donnée pour {symbol}"}

        # Indicateurs
        close = hist["Close"]
        hist["SMA50"] = close.rolling(50).mean()
        hist["SMA200"] = close.rolling(200).mean()
        hist["RSI"] = compute_rsi(close)

        last = hist.iloc[-1]
        prev = hist.iloc[-2] if len(hist) > 1 else last

        return {
            "symbol": symbol,
            "company": ticker.info.get("longName", symbol),
            "price": float(last["Close"]),
            "change_pct": ((last["Close"] - prev["Close"]) / prev["Close"] * 100) if len(hist) > 1 else 0.0,
            "volume": int(last["Volume"]),
            "sma50": float(last["SMA50"]) if not pd.isna(last["SMA50"]) else None,
            "sma200": float(last["SMA200"]) if not pd.isna(last["SMA200"]) else None,
            "rsi": float(last["RSI"]) if not pd.isna(last["RSI"]) else None,
            "trend": "haussière" if last["SMA50"] > last["SMA200"] else "baissière" if last["SMA50"] < last["SMA200"] else "latérale",
            "days": len(hist),
            "last_5_days": hist[["Close", "Volume"]].tail().to_dict()
        }
    except Exception as e:
        return {"error": f"Erreur données {symbol}: {str(e)}"}

def compute_rsi(prices, window=14):
    delta = prices.diff()
    gain = (delta.where(delta > 0, 0)).rolling(window=window).mean()
    loss = (-delta.where(delta < 0, 0)).rolling(window=window).mean()
    rs = gain / loss
    rsi = 100 - (100 / (1 + rs))
    return rsi

# --------------------------------------------------------------------------- #
# UTILS
# --------------------------------------------------------------------------- #
def now_ts() -> str:
    return datetime.utcnow().isoformat() + "Z"

def append_log(entry: dict):
    try:
        data = json.loads(LOG_FILE.read_text()) if LOG_FILE.exists() else []
        data.append(entry)
        LOG_FILE.write_text(json.dumps(data, indent=2, ensure_ascii=False))
    except Exception:
        pass

# --------------------------------------------------------------------------- #
# BOUCLE CONVERSATIONNELLE
# --------------------------------------------------------------------------- #
def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", "-s", default="SPY", help="Symbole à analyser")
    args = parser.parse_args()

    console.clear()
    console.rule(f"[bold]{AGENT_NAME} v7[/bold] — {args.symbol} — [green]Gemini au cœur[/green]")
    console.print("[dim]💬 Je suis ton agent IA de trading. Pose-moi n'importe quelle question.[/dim]\n")

    # Récupérer le contexte marché
    with Progress(SpinnerColumn(), TextColumn("Chargement des données marché..."), transient=True) as pg:
        pg.add_task("", total=None)
        context = get_market_context(args.symbol)

    if "error" in context:
        console.print(f"[red] {context['error']}[/red]")
        return


    system_prompt = (
        "Tu es Atlas Trader, un agent IA expert en trading dont l'objectif est d'aider l'utilisateur à s'enrichir prudemment. "
        "Meme si il a pas assez de fond pour debuter en trading,"
        "Tu as accès a des donnees de marche en temps reel. "
        "Règles :\n"
        "1. Sois clair, direct, et actionnable.\n"
        "2. Si le marché est favorable, propose un trade spécifique (symbole, direction, raisonnement, et l'action).\n"
        "3. Explique toujours le 'pourquoi' (tendance, RSI, volume, etc.).\n"
        "4. Gère le risque : ne jamais proposer de levier excessif.\n"
        "5. Si tu recommandes un achat/vente/etc, précise la taille relative (ex: 1% du capital).\n"
        "6. Parle comme un trader humain, pas comme un robot.,"
        "7. N'hallucine jamais ou ne donne jamais de fausses actions. "
        "8. Tu dois repondre brevement et aller droit au but pour ne pas prendre trop d'espace dans le terminal"
        "9. "
    )

    # Premier message de Gemini
    market_summary = (
        f"Symbole: {context['symbol']} ({context['company']})\n"
        f"Prix actuel: {context['price']:.2f} USD\n"
        f"Variation: {context['change_pct']:.2f}%\n"
        f"Volume: {context['volume']:,}\n"
        f"Tendance: {context['trend']}\n"
        f"RSI: {context['rsi']:.1f} si dispo\n"
        f"Données: {context['days']} jours historiques"
    )

    with Progress(SpinnerColumn(), TextColumn("Gemini analyse le marché..."), transient=True) as pg:
        pg.add_task("", total=None)
        first_response = ask_gemini(system_prompt, market_summary)

    console.print(Panel(Markdown(first_response), title=" Atlas Trader (Gemini)", border_style="cyan"))

    # Boucle conversationnelle
    while True:
        try:
            question = Prompt.ask("\n[bold cyan] Vous : [/bold cyan]").strip()
            if not question or question.lower() in ("quit", "exit", "q"):
                break

            # Mettre à jour le contexte (au cas où)
            context = get_market_context(args.symbol)
            if "error" not in context:
                market_summary = (
                    f"Symbole: {context['symbol']} ({context['company']})\n"
                    f"Prix: {context['price']:.2f} USD\n"
                    f"Tendance: {context['trend']}, RSI: {context['rsi']:.1f}\n"
                    f"Volume: {context['volume']:,}"
                )
                user_prompt = f"{market_summary}\n\nQUESTION UTILISATEUR:\n{question}"
            else:
                user_prompt = f"Erreur données: {context['error']}\n\nQUESTION UTILISATEUR:\n{question}"

            with Progress(SpinnerColumn(), TextColumn("Gemini réfléchit..."), transient=True) as pg:
                pg.add_task("", total=None)
                response = ask_gemini(system_prompt, user_prompt)

            console.print(Panel(Markdown(response), title=" Atlas Trader (Gemini)", border_style="cyan"))

        except KeyboardInterrupt:
            break
        except Exception as e:
            console.print(Panel(f"[red]{e}[/red]", title="Erreur", border_style="red"))

    console.print("[bold green]Merci d'avoir utilisé Atlas Trader v7 ![/bold green]")

if __name__ == "__main__":
    main()