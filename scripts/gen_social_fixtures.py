"""Generate the deterministic, offline consumer-trend fixture corpus.

Usage: .venv/bin/python scripts/gen_social_fixtures.py [--scale 1.0]

Writes under tests/fixtures/social/:
  reddit_posts.jsonl   synthetic Reddit posts with ground-truth entity extraction
  pageviews.json       daily Wikipedia pageviews per article, 63 days
  news_items.jsonl     financial-news headlines per canonical entity
  README.md            the designed trend shapes and expected scoring outcomes

Everything is driven by one seeded ``random.Random`` (seed 20261027) so the output is
byte-identical across runs. Stdlib only.

``--scale`` multiplies every entity's daily Reddit rate. The default 0.6 keeps the corpus
under 3 MB (~4,700 posts) while preserving every trend SHAPE (ratios, sentiment drift,
campaign, author burst); ``--scale 1.0`` reproduces the literal per-entity rates in the spec
(~8,000 posts).
"""

from __future__ import annotations

import argparse
import json
import math
import random
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

SEED = 20261027
DEFAULT_SCALE = 0.6
START_DAY = date(2026, 8, 26)
N_DAYS = 63
RECENT_DAYS = 7  # 2026-10-21 .. 2026-10-27
BASELINE_DAYS = N_DAYS - RECENT_DAYS
OUT_DIR = Path(__file__).resolve().parents[1] / "tests" / "fixtures" / "social"

CONSUMER_SUBS = (
    "HydroHomies",
    "BuyItForLife",
    "running",
    "sneakers",
    "SkincareAddiction",
    "MakeupAddiction",
    "fastfood",
    "Costco",
    "gadgets",
    "gaming",
    "Coffee",
    "energydrinks",
    "teenagers",
    "femalefashionadvice",
    "malefashionadvice",
    "Fitness",
    "Frugal",
    "electricvehicles",
)
STOCK_SUBS = ("wallstreetbets", "stocks", "investing", "options", "thetagang")

N_AUTHORS = 600
N_BOT_AUTHORS = 24
BOT_POST_FRACTION = 0.03
EMPTY_ENTITY_FRACTION = 0.12
CO_MENTION_P = 0.08
SPAM_CAMPAIGN_POSTS = 40
PROLIFIC_OWALA_POSTS = 25

# UTC hour weights: US daytime/evening (13:00-04:00 UTC) dominates.
HOUR_WEIGHTS = [4, 3, 3, 2, 1, 1, 1, 1, 2, 2, 3, 4, 6, 8, 9, 10, 10, 10, 10, 9, 8, 7, 6, 5]


# --------------------------------------------------------------------------------------
# Entity specification
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class EntitySpec:
    name: str
    etype: str  # product | brand | company | store
    cluster: str
    base_rate: float  # Reddit mentions/day, baseline weeks
    recent_rate: float  # Reddit mentions/day, last 7 days
    sent_start: float
    sent_end: float
    purchase_p: float
    subs: tuple[str, ...]
    aliases: tuple[str, ...]
    stock_aliases: tuple[str, ...]
    stock_frac: float  # share of posts that are stock talk in stock subs
    wiki: str
    pv_base: int
    pv_mult: float  # pageview multiplier reached by the end of the last week
    news_base: float  # news items/day baseline
    news_recent: float
    parent: str
    ticker: str | None
    headlines: tuple[str, ...]
    outcome: str  # designed scoring outcome, for the README


ENTITIES: tuple[EntitySpec, ...] = (
    EntitySpec(
        "Owala",
        "brand",
        "bottles",
        2,
        12,
        0.7,
        0.7,
        0.7,
        ("HydroHomies", "BuyItForLife", "Fitness", "teenagers", "Frugal"),
        ("Owala", "owala", "Owala FreeSip", "owala freesip"),
        (),
        0.0,
        "Owala",
        1500,
        4.0,
        0.05,
        0.05,
        "Owala",
        None,
        (
            "Owala parent Trove Brands quietly expands FreeSip production",
            "The water bottle wars: Owala takes aim at Stanley's crown",
            "Owala launches limited-edition fall colorways amid retail sellouts",
            "Retailers report Owala stockouts heading into holiday season",
            "How Owala became the bottle Gen Z actually wants",
            "Owala adds Target end-caps as demand outpaces supply",
        ),
        "HIGH: breakout + coverage gap (Reddit 6x, news flat). Private parent -> not directly investable; surfaces as a signal only.",
    ),
    EntitySpec(
        "Stanley Quencher",
        "product",
        "bottles",
        8,
        3,
        0.4,
        -0.1,
        0.3,
        ("HydroHomies", "BuyItForLife", "teenagers", "femalefashionadvice"),
        ("Stanley", "stanley", "Stanley Quencher", "stanley cup", "stanley tumbler"),
        (),
        0.0,
        "Stanley (brand)",
        6000,
        0.6,
        0.3,
        0.3,
        "Stanley",
        None,
        (
            "Stanley Quencher craze cools as resale prices slide",
            "Stanley parent PMI faces lead-exposure lawsuit over tumblers",
            "Stanley's 2023 viral moment is fading, data shows",
            "Stanley bets on new tumbler sizes to revive growth",
            "Stanley Quencher restocks no longer sell out, retailers say",
            "After the Quencher boom, Stanley searches for its next hit",
        ),
        "LOW: fading (8 -> 3/day) with sentiment turning sarcastic.",
    ),
    EntitySpec(
        "HOKA",
        "brand",
        "footwear",
        3,
        9,
        0.6,
        0.6,
        0.6,
        ("running", "sneakers", "Fitness", "malefashionadvice"),
        ("HOKA", "Hoka", "hokas", "hoka clifton", "Hoka Bondi", "hoka"),
        ("DECK", "deckers"),
        0.05,
        "Hoka One One",
        2500,
        2.5,
        0.5,
        0.9,
        "Deckers Outdoor",
        "DECK",
        (
            "Deckers raises outlook as HOKA demand holds",
            "HOKA sales jump 30% as Deckers leans on running boom",
            "Deckers' HOKA brand on pace to overtake UGG, analysts say",
            "HOKA opens flagship stores in push beyond specialty running",
            "Deckers shares climb on strong HOKA wholesale orders",
            "HOKA Clifton 10 launch drives record traffic, Deckers says",
            "Is HOKA the next Nike? Deckers investors bet yes",
        ),
        "HIGH: strong rise (3 -> 9/day), positive, purchase intent, news only slightly up.",
    ),
    EntitySpec(
        "Crocs",
        "brand",
        "footwear",
        3,
        7,
        0.5,
        0.5,
        0.5,
        ("sneakers", "teenagers", "Frugal", "femalefashionadvice"),
        ("Crocs", "crocs", "my crocs", "Crocs clogs"),
        ("CROX",),
        0.05,
        "Crocs",
        3500,
        1.8,
        0.4,
        0.4,
        "Crocs",
        "CROX",
        (
            "Crocs lifts guidance as clog demand holds up",
            "Crocs' HEYDUDE unit remains a drag despite core brand strength",
            "Crocs taps new collaborations to keep Gen Z engaged",
            "Crocs shares rise after beating third-quarter estimates",
            "Crocs expands Asia footprint with new store openings",
            "Why Crocs stock is outrunning the footwear sector this year",
        ),
        "MEDIUM-HIGH: rise (3 -> 7/day), positive.",
    ),
    EntitySpec(
        "On Cloud",
        "brand",
        "footwear",
        2,
        4,
        0.5,
        0.5,
        0.5,
        ("running", "sneakers", "malefashionadvice"),
        ("On Cloud", "On Clouds", "on clouds", "On Cloudmonster", "on running"),
        ("ONON",),
        0.05,
        "On (company)",
        1800,
        1.6,
        0.3,
        0.3,
        "On Holding",
        "ONON",
        (
            "On Holding raises full-year outlook on strong Cloud franchise",
            "On's Cloudmonster drives double-digit growth in Americas",
            "Swiss running brand On opens new flagship in Paris",
            "On Holding shares jump after beating sales expectations",
            "On Holding sees margin expansion as DTC mix grows",
            "Roger Federer-backed On eyes apparel push beyond footwear",
        ),
        "MEDIUM: moderate rise (2 -> 4/day).",
    ),
    EntitySpec(
        "Celsius",
        "brand",
        "beverages",
        10,
        10,
        0.3,
        0.3,
        0.4,
        ("energydrinks", "Fitness", "teenagers", "Costco"),
        ("Celsius", "celsius", "a celsius", "Celsius energy"),
        ("CELH",),
        0.05,
        "Celsius Holdings",
        4000,
        1.0,
        2.5,
        2.5,
        "Celsius Holdings",
        "CELH",
        (
            "Celsius Holdings posts record revenue as energy drink share grows",
            "Celsius shares fall as PepsiCo inventory adjustments weigh",
            "Celsius expands into Canada and UK with PepsiCo distribution",
            "Celsius Holdings completes Alani Nu acquisition",
            "Analyst: Celsius growth is slowing but still leading the category",
            "Celsius launches new flavors ahead of holiday season",
            "Celsius Holdings stock: can the energy drink maker keep its momentum?",
        ),
        "LOW: hot the whole window (10/day flat) and heavily covered -> no novelty, no coverage gap.",
    ),
    EntitySpec(
        "e.l.f.",
        "brand",
        "beauty",
        3,
        7,
        0.6,
        0.6,
        0.6,
        ("SkincareAddiction", "MakeupAddiction", "teenagers"),
        ("e.l.f.", "elf", "ELF", "e.l.f", "elf cosmetics"),
        ("ELF",),
        0.05,
        "E.l.f. Cosmetics",
        1200,
        1.9,
        0.5,
        0.5,
        "e.l.f. Beauty",
        "ELF",
        (
            "e.l.f. Beauty raises guidance as market share gains continue",
            "e.l.f. Beauty shares surge after Rhode acquisition closes",
            "e.l.f. gains share for 25th straight quarter, Nielsen data shows",
            "e.l.f. Beauty expands into Sephora with new skincare line",
            "Why e.l.f. Beauty keeps winning with Gen Z shoppers",
            "e.l.f. Beauty beats estimates, flags tariff headwinds",
        ),
        "MEDIUM-HIGH: rise (3 -> 7/day), positive, purchase intent, teen-heavy subs.",
    ),
    EntitySpec(
        "Kirkland Signature",
        "brand",
        "costco",
        5,
        5,
        0.5,
        0.5,
        0.4,
        ("Costco", "Frugal", "BuyItForLife"),
        ("Kirkland Signature", "Kirkland", "kirkland", "KS"),
        (),
        0.0,
        "Kirkland Signature",
        2200,
        1.0,
        0.1,
        0.1,
        "Costco Wholesale",
        None,
        (
            "Kirkland Signature now a $80 billion brand, Costco says",
            "Costco's Kirkland Signature tops private-label trust rankings",
            "Costco adds Kirkland Signature sparkling water line",
            "Kirkland Signature vodka maker revealed, sort of",
            "Costco leans on Kirkland Signature as shoppers trade down",
            "Kirkland Signature expands into pet food and supplements",
        ),
        "LOW-MEDIUM: steady 5/day, positive; no acceleration.",
    ),
    EntitySpec(
        "Costco",
        "store",
        "costco",
        6,
        6,
        0.4,
        0.4,
        0.3,
        ("Costco", "Frugal"),
        ("Costco", "costco", "the warehouse"),
        ("COST",),
        0.05,
        "Costco",
        9000,
        1.0,
        1.5,
        1.5,
        "Costco Wholesale",
        "COST",
        (
            "Costco comparable sales rise as membership renewals hold at 90%",
            "Costco raises membership fee for first time since 2017",
            "Costco's e-commerce growth accelerates on big-ticket items",
            "Costco opens 30 new warehouses in fiscal year",
            "Costco stock: premium valuation faces test as growth normalizes",
            "Costco cracks down on membership sharing at entrances",
            "Costco gold bar sales continue to surprise analysts",
        ),
        "LOW-MEDIUM: steady 6/day, positive; well covered by news.",
    ),
    EntitySpec(
        "Dutch Bros",
        "company",
        "coffee",
        2,
        5,
        0.6,
        0.6,
        0.5,
        ("Coffee", "teenagers", "fastfood"),
        ("Dutch Bros", "dutch bros", "Dutch", "dutch"),
        ("BROS",),
        0.05,
        "Dutch Bros",
        1600,
        1.8,
        0.4,
        0.4,
        "Dutch Bros",
        "BROS",
        (
            "Dutch Bros raises outlook as same-shop sales accelerate",
            "Dutch Bros shares jump on strong traffic growth",
            "Dutch Bros plans 160 new shops as expansion heads east",
            "Dutch Bros mobile ordering drives loyalty gains",
            "Dutch Bros adds food menu in test markets",
            "Why Dutch Bros is beating Starbucks at its own game",
        ),
        "MEDIUM-HIGH: rise (2 -> 5/day), positive.",
    ),
    EntitySpec(
        "CAVA",
        "company",
        "restaurants",
        1,
        6,
        0.7,
        0.7,
        0.6,
        ("fastfood", "Fitness", "Frugal"),
        ("CAVA", "Cava", "cava"),
        ("CAVA",),
        0.05,
        "Cava (restaurant)",
        900,
        3.5,
        0.1,
        0.1,
        "Cava Group",
        "CAVA",
        (
            "Cava Group reports strong same-restaurant sales growth",
            "CAVA expands into Midwest with 15 new restaurants",
            "Cava shares climb as traffic defies restaurant slowdown",
            "CAVA launches loyalty program revamp",
            "Is Cava the next Chipotle? Investors hope so",
            "Cava Group guides for 60 new restaurant openings",
        ),
        "HIGH: breakout (1 -> 6/day), positive, purchase intent, news flat (coverage gap).",
    ),
    EntitySpec(
        "Lululemon",
        "company",
        "apparel",
        4,
        4,
        0.1,
        0.1,
        0.3,
        ("Fitness", "femalefashionadvice", "running"),
        ("Lululemon", "lululemon", "lulu", "Lulu"),
        ("LULU",),
        0.05,
        "Lululemon Athletica",
        4500,
        1.0,
        1.0,
        1.0,
        "Lululemon Athletica",
        "LULU",
        (
            "Lululemon cuts outlook as US sales stall",
            "Lululemon shares slide on weak Americas comps",
            "Lululemon faces competition from Alo and Vuori in core market",
            "Lululemon's international growth offsets domestic weakness",
            "Lululemon launches new product line to reignite US demand",
            "Lululemon CEO under pressure as stock lags peers",
        ),
        "LOW: flat 4/day, near-neutral sentiment.",
    ),
    EntitySpec(
        "Nike",
        "company",
        "apparel",
        6,
        6,
        0.2,
        -0.3,
        0.2,
        ("sneakers", "running", "malefashionadvice", "teenagers"),
        ("Nike", "nike", "nikes", "Nikes"),
        ("NKE", "nike"),
        0.08,
        "Nike, Inc.",
        14000,
        1.0,
        1.5,
        1.5,
        "Nike",
        "NKE",
        (
            "Nike sales fall again as turnaround drags on",
            "Nike shares drop after warning on China demand",
            "Nike's new CEO bets on running to win back customers",
            "Nike cuts jobs in latest restructuring round",
            "Nike faces tariff hit of $1 billion, CFO says",
            "Nike inventory glut forces deeper discounts",
            "Nike stock: is the worst over for the sneaker giant?",
        ),
        "LOW: flat 6/day with sentiment sliding to -0.3; well covered.",
    ),
    EntitySpec(
        "Chipotle",
        "company",
        "restaurants",
        5,
        5,
        -0.4,
        -0.4,
        0.2,
        ("fastfood", "Frugal", "teenagers"),
        ("Chipotle", "chipotle", "Chipotle's"),
        ("CMG",),
        0.06,
        "Chipotle Mexican Grill",
        7000,
        1.0,
        1.2,
        1.2,
        "Chipotle Mexican Grill",
        "CMG",
        (
            "Chipotle cuts outlook as traffic declines for second quarter",
            "Chipotle shares fall on weaker-than-expected comparable sales",
            "Chipotle portion-size backlash hits brand perception, survey finds",
            "Chipotle to open 300 restaurants next year despite slowdown",
            "Chipotle raises menu prices to offset tariff costs",
            "Chipotle's new CEO faces pressure to revive traffic",
        ),
        "LOW: flat 5/day, negative (portion sizes), moderate news.",
    ),
    EntitySpec(
        "Starbucks",
        "company",
        "coffee",
        6,
        3,
        -0.3,
        -0.3,
        0.2,
        ("Coffee", "fastfood", "Frugal"),
        ("Starbucks", "starbucks", "Starbs", "sbux"),
        ("SBUX", "sbux"),
        0.08,
        "Starbucks",
        16000,
        0.8,
        1.5,
        1.5,
        "Starbucks",
        "SBUX",
        (
            "Starbucks same-store sales fall for sixth straight quarter",
            "Starbucks to close underperforming stores in turnaround push",
            "Starbucks CEO Niccol's 'Back to Starbucks' plan shows early signs",
            "Starbucks cuts 1,100 corporate jobs",
            "Starbucks shares slip as China sales disappoint",
            "Starbucks tests new menu to speed up service times",
            "Starbucks baristas strike at hundreds of stores",
        ),
        "LOW: declining (6 -> 3/day), negative.",
    ),
    EntitySpec(
        "AirPods",
        "product",
        "gadgets",
        4,
        4,
        0.3,
        0.3,
        0.4,
        ("gadgets", "running", "teenagers"),
        ("AirPods", "airpods", "AirPods Pro", "airpod pros"),
        (),
        0.0,
        "AirPods",
        11000,
        1.0,
        0.5,
        0.5,
        "Apple",
        "AAPL",
        (
            "Apple's AirPods Pro 3 add heart-rate sensing and live translation",
            "AirPods sales steady as wearables segment flattens, Apple says",
            "Apple AirPods gain FDA clearance for hearing aid feature",
            "AirPods Max refresh lands with USB-C and new colors",
            "Apple expands AirPods production in Vietnam",
            "AirPods remain top-selling earbuds despite cheaper rivals",
        ),
        "LOW-MEDIUM: steady 4/day, mildly positive.",
    ),
    EntitySpec(
        "Sweetgreen",
        "company",
        "restaurants",
        2,
        2,
        0.0,
        0.0,
        0.2,
        ("fastfood", "Fitness"),
        ("Sweetgreen", "sweetgreen", "SG"),
        ("SG",),
        0.05,
        "Sweetgreen",
        700,
        1.0,
        0.3,
        0.3,
        "Sweetgreen",
        "SG",
        (
            "Sweetgreen cuts guidance as same-store sales turn negative",
            "Sweetgreen shares tumble on weak traffic",
            "Sweetgreen rolls out Infinite Kitchen automation to more stores",
            "Sweetgreen launches lower-priced menu to win back customers",
            "Sweetgreen slows new store openings amid demand slump",
            "Sweetgreen CEO says loyalty program is key to recovery",
        ),
        "LOW: flat 2/day, neutral.",
    ),
    EntitySpec(
        "Oura Ring",
        "product",
        "gadgets",
        2,
        5,
        0.5,
        0.5,
        0.5,
        ("gadgets", "Fitness"),
        ("Oura Ring", "Oura", "oura", "oura ring"),
        (),
        0.0,
        "Oura Health",
        1300,
        1.9,
        0.1,
        0.1,
        "Oura Health",
        None,
        (
            "Oura valuation tops $10 billion in new funding round",
            "Oura Ring 4 launch drives record sales, company says",
            "Oura partners with Dexcom on glucose tracking",
            "Oura expands into retail with Target rollout",
            "Oura sues Ultrahuman and RingConn over patents",
            "Oura CEO says IPO is 'not a priority' despite growth",
        ),
        "MEDIUM signal but NOT investable (private).",
    ),
    EntitySpec(
        "Liquid Death",
        "brand",
        "beverages",
        2,
        2,
        0.2,
        0.2,
        0.3,
        ("energydrinks", "HydroHomies", "teenagers"),
        ("Liquid Death", "liquid death", "LD"),
        (),
        0.0,
        "Liquid Death",
        1100,
        1.0,
        0.05,
        0.05,
        "Liquid Death",
        None,
        (
            "Liquid Death raises funding at $1.4 billion valuation",
            "Liquid Death expands into iced tea and energy",
            "Liquid Death's marketing playbook: murder your thirst",
            "Liquid Death lands national distribution deal with Costco",
            "Liquid Death explores sale or IPO, sources say",
            "Liquid Death launches limited-edition flavors with Yeti",
        ),
        "LOW: flat 2/day (private).",
    ),
    EntitySpec(
        "Olipop",
        "brand",
        "beverages",
        2,
        5,
        0.5,
        0.5,
        0.5,
        ("energydrinks", "Frugal", "Fitness"),
        ("Olipop", "olipop", "OLIPOP"),
        (),
        0.0,
        "Olipop",
        800,
        1.7,
        0.05,
        0.05,
        "Olipop",
        None,
        (
            "Olipop valued at $1.85 billion in latest funding round",
            "Olipop tops $500 million in annual sales as soda category shifts",
            "Olipop expands to Costco nationwide",
            "Olipop and Poppi battle for prebiotic soda shelf space",
            "Olipop launches new flavor with Barbie tie-in",
            "Olipop CEO: 'We're not for sale' amid PepsiCo rumors",
        ),
        "MEDIUM organic rise (2 -> 5/day) PLUS a 40-post spam campaign the dedupe/bot filter must remove. Private.",
    ),
    EntitySpec(
        "Poppi",
        "brand",
        "beverages",
        2,
        4,
        0.4,
        0.4,
        0.4,
        ("energydrinks", "teenagers", "Fitness"),
        ("Poppi", "poppi", "a poppi"),
        (),
        0.0,
        "Poppi (drink)",
        900,
        1.5,
        0.05,
        0.05,
        "Poppi",
        None,
        (
            "PepsiCo completes $1.95 billion acquisition of Poppi",
            "Poppi settles class action over gut-health claims",
            "Poppi expands distribution under PepsiCo ownership",
            "Poppi Super Bowl ad backlash: vending machine stunt draws criticism",
            "Poppi launches new flavors as prebiotic soda category grows",
            "PepsiCo says Poppi integration is ahead of schedule",
        ),
        "MEDIUM: rise (2 -> 4/day). Now owned by PepsiCo.",
    ),
    EntitySpec(
        "Birkenstock",
        "company",
        "footwear",
        2,
        3,
        0.4,
        0.4,
        0.4,
        ("femalefashionadvice", "malefashionadvice", "BuyItForLife"),
        ("Birkenstock", "birkenstocks", "birks", "Birks"),
        ("BIRK",),
        0.05,
        "Birkenstock",
        3200,
        1.2,
        0.3,
        0.3,
        "Birkenstock Holding",
        "BIRK",
        (
            "Birkenstock raises guidance as closed-toe styles gain traction",
            "Birkenstock shares rise on strong Americas growth",
            "Birkenstock expands production capacity in Germany",
            "Birkenstock wins legal fight over clog design",
            "Birkenstock's premium pricing holds despite tariff pressure",
            "Birkenstock opens new stores in Asia-Pacific push",
        ),
        "LOW-MEDIUM: slow rise (2 -> 3/day).",
    ),
    EntitySpec(
        "Xbox Game Pass",
        "product",
        "gaming",
        3,
        3,
        -0.2,
        -0.2,
        0.2,
        ("gaming", "teenagers", "Frugal"),
        ("Xbox Game Pass", "Game Pass", "game pass", "gamepass", "GP"),
        (),
        0.0,
        "Xbox Game Pass",
        5500,
        1.1,
        0.4,
        0.4,
        "Microsoft",
        "MSFT",
        (
            "Microsoft raises Xbox Game Pass Ultimate price to $29.99",
            "Xbox Game Pass subscriber growth stalls, Microsoft says",
            "Microsoft adds Fortnite and Call of Duty to Game Pass tiers",
            "Xbox Game Pass price hike sparks cancellation wave",
            "Microsoft defends Game Pass economics amid developer concerns",
            "Xbox Game Pass heads to more devices in cloud push",
        ),
        "LOW: steady 3/day, negative (price hikes).",
    ),
    EntitySpec(
        "Abercrombie",
        "company",
        "apparel",
        2,
        5,
        0.5,
        0.5,
        0.5,
        ("femalefashionadvice", "malefashionadvice", "teenagers"),
        ("Abercrombie", "abercrombie", "A&F", "a&f"),
        ("ANF",),
        0.05,
        "Abercrombie & Fitch",
        2800,
        1.8,
        0.4,
        0.4,
        "Abercrombie & Fitch",
        "ANF",
        (
            "Abercrombie & Fitch raises outlook as Hollister growth surprises",
            "Abercrombie shares jump after beating estimates",
            "Abercrombie's turnaround keeps delivering, analysts say",
            "Abercrombie & Fitch expands wedding shop and curve love lines",
            "Abercrombie flags tariff costs but keeps full-year outlook",
            "Abercrombie & Fitch stock: valuation still cheap after rally?",
        ),
        "MEDIUM-HIGH: rise (2 -> 5/day), positive.",
    ),
    EntitySpec(
        "Trader Joe's",
        "store",
        "grocery",
        4,
        4,
        0.5,
        0.5,
        0.4,
        ("Frugal", "Fitness", "BuyItForLife"),
        ("Trader Joe's", "trader joes", "TJ's", "tjs"),
        (),
        0.0,
        "Trader Joe's",
        6500,
        1.0,
        0.1,
        0.1,
        "Trader Joe's",
        None,
        (
            "Trader Joe's tops grocery customer satisfaction rankings again",
            "Trader Joe's mini tote bags spark resale frenzy",
            "Trader Joe's plans 30 new stores in expansion push",
            "Trader Joe's recalls frozen item over listeria concerns",
            "Inside Trader Joe's private-label strategy",
            "Trader Joe's workers vote to unionize at third store",
        ),
        "LOW-MEDIUM: steady 4/day, positive, NOT investable (private).",
    ),
    EntitySpec(
        "Uniqlo",
        "brand",
        "apparel",
        1,
        3,
        0.5,
        0.5,
        0.5,
        ("malefashionadvice", "femalefashionadvice", "Frugal"),
        ("Uniqlo", "uniqlo", "UNIQLO"),
        (),
        0.0,
        "Uniqlo",
        4200,
        1.4,
        0.2,
        0.2,
        "Fast Retailing",
        None,
        (
            "Fast Retailing lifts forecast as Uniqlo North America sales surge",
            "Uniqlo to open 20 new US stores in expansion push",
            "Uniqlo parent Fast Retailing posts record profit",
            "Uniqlo's Heattech and Airism lines drive overseas growth",
            "Fast Retailing warns tariffs will squeeze Uniqlo US margins",
            "Uniqlo bets on Texas as it chases Zara and H&M",
        ),
        "MEDIUM signal but not US-listed (Fast Retailing, Tokyo).",
    ),
    EntitySpec(
        "GameStop",
        "company",
        "stock",
        6,
        15,
        0.3,
        0.4,
        0.0,
        ("wallstreetbets", "stocks", "options"),
        ("GameStop", "GME", "gamestop", "gme"),
        ("GME", "GameStop", "gamestop", "gme"),
        1.0,
        "GameStop",
        9000,
        2.0,
        0.8,
        0.8,
        "GameStop",
        "GME",
        (
            "GameStop shares spike as retail traders pile back in",
            "GameStop raises $2 billion in convertible note offering",
            "GameStop adds bitcoin to treasury, shares swing",
            "GameStop sales fall as store closures continue",
            "GameStop's Ryan Cohen hints at acquisition strategy",
            "GameStop short interest climbs ahead of earnings",
            "Why GameStop stock is rallying again",
        ),
        "PENALISED: all mentions are stock-sub hype (is_stock_talk=True), 6 -> 15/day. Zero consumer signal.",
    ),
    EntitySpec(
        "Tesla",
        "company",
        "ev",
        8,
        12,
        0.1,
        0.1,
        0.3,
        ("electricvehicles", "gadgets"),
        ("Tesla", "tesla", "my Tesla", "Model Y", "Model 3"),
        ("TSLA", "tesla", "Tesla"),
        0.7,
        "Tesla, Inc.",
        40000,
        1.3,
        5.0,
        5.0,
        "Tesla",
        "TSLA",
        (
            "Tesla deliveries fall short of estimates for third quarter",
            "Tesla shares rise on robotaxi expansion plans",
            "Tesla Model Y refresh boosts China sales",
            "Tesla cuts prices in Europe as competition intensifies",
            "Musk's pay package approved by Tesla shareholders",
            "Tesla FSD subscription growth lifts software revenue",
            "Tesla energy storage deployments hit record",
            "Tesla faces NHTSA probe over Full Self-Driving incidents",
        ),
        "MIXED/PENALISED: 70% stock-sub hype; 30% consumer EV posts. Saturated news coverage.",
    ),
)
ENTITY_BY_NAME = {e.name: e for e in ENTITIES}

# Related entities that occasionally show up as a second mention in a post.
CO_MENTIONS: dict[str, tuple[str, ...]] = {
    "Owala": ("Stanley Quencher",),
    "Stanley Quencher": ("Owala",),
    "HOKA": ("On Cloud", "Nike"),
    "On Cloud": ("HOKA",),
    "Crocs": ("Birkenstock",),
    "Birkenstock": ("Crocs",),
    "Celsius": ("Poppi", "Costco"),
    "Liquid Death": ("Celsius",),
    "Olipop": ("Poppi",),
    "Poppi": ("Olipop",),
    "Kirkland Signature": ("Costco",),
    "Costco": ("Kirkland Signature", "Celsius"),
    "Dutch Bros": ("Starbucks",),
    "Starbucks": ("Dutch Bros",),
    "CAVA": ("Chipotle", "Sweetgreen"),
    "Chipotle": ("CAVA",),
    "Sweetgreen": ("CAVA",),
    "Lululemon": ("Nike",),
    "Nike": ("HOKA",),
    "Abercrombie": ("Uniqlo",),
    "Uniqlo": ("Abercrombie",),
    "AirPods": ("Oura Ring",),
    "Oura Ring": ("AirPods",),
    "Trader Joe's": ("Costco",),
}


# --------------------------------------------------------------------------------------
# Post text is COMPOSED from slots so ordinary posts are lexically diverse (real Reddit
# posts almost never repeat verbatim; only the designed Olipop campaign does).
#   body  = [opener] + experience + detail [+ detail] + [sign-off]   (3-5 slots)
#   title = lead + tail                                                (2 slots)
# ``{e}`` is the entity alias; the other placeholders are filled per post from FILLS.
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Slots:
    title_pos: tuple[str, ...]
    title_neg: tuple[str, ...]
    exp_pos: tuple[str, ...]
    exp_neg: tuple[str, ...]
    detail: tuple[str, ...]


OPENERS = (
    "ngl",
    "ok so",
    "update:",
    "so",
    "long time lurker here.",
    "quick one -",
    "not sponsored lol.",
    "hear me out.",
    "psa:",
    "alright,",
    "real talk,",
    "idk if this is allowed but",
)
SIGNOFF_POS = (
    "anyone else?",
    "worth it imo.",
    "10/10 would recommend.",
    "thats the post.",
    "happy to answer questions.",
    "not an ad i promise.",
    "edit: thanks for the awards lol",
    "ymmv obviously.",
    "ok bye.",
    "anyway. thats my review.",
)
SIGNOFF_NEG = (
    "am i crazy?",
    "anyone else or just me?",
    "rant over.",
    "do better.",
    "returning it tomorrow.",
    "never again.",
    "change my mind.",
    "idk man.",
    "edit: typo",
    "thats it thats the post.",
)
TITLE_TAILS = (
    "",
    "",
    "",
    " - thoughts?",
    " (long post)",
    ", anyone else?",
    " [update]",
    " - worth it?",
    " lol",
    " (rant)",
    ", help",
    " ??",
)
EMOJIS = ("🙃", "😭", "🔥", "💀", "🥲", "👀", "🤷", "✨", "😤", "🫠")
INTERJECTIONS = (" lol", " tbh", " fr", " honestly", " ngl", " lmao")

FILLS: dict[str, tuple[str, ...]] = {
    "color": ("black", "sage", "navy", "lilac", "white", "coral", "olive", "cream", "grey", "teal"),
    "color2": ("pink", "forest green", "sand", "burgundy", "sky blue", "charcoal", "mint", "rust"),
    "size": ("24oz", "32oz", "40oz", "small", "medium", "large", "xs", "xl"),
    "store": (
        "Target",
        "Costco",
        "Amazon",
        "Dicks",
        "REI",
        "Ulta",
        "Walmart",
        "Nordstrom",
        "Best Buy",
        "the outlet",
    ),
    "city": (
        "Denver",
        "Austin",
        "Phoenix",
        "Portland",
        "Chicago",
        "Atlanta",
        "Seattle",
        "Tampa",
        "Boise",
        "Columbus",
        "Raleigh",
        "Sacramento",
    ),
    "day": ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"),
    "month": ("january", "march", "april", "june", "august", "september", "november", "december"),
    "flavor": ("peach", "orange", "grape", "vanilla", "pumpkin", "mango", "cherry", "lime"),
    "protein": ("chicken", "steak", "falafel", "lamb", "tofu", "shrimp"),
    "shade": ("fair", "light", "light medium", "medium", "tan", "deep"),
}


def make_fills(rng) -> dict[str, Any]:
    fills: dict[str, Any] = {k: rng.choice(v) for k, v in FILLS.items()}
    fills.update(
        n=rng.randint(2, 12),
        n2=rng.randint(2, 9),
        big=rng.randint(20, 500),
        weeks=rng.randint(2, 10),
        price=rng.choice((8, 12, 15, 19, 24, 29, 34, 45, 59, 79, 98, 118, 140, 160)),
        price2=rng.choice((9, 14, 18, 22, 27, 39, 49, 69, 89, 129)),
        shoe=rng.randint(7, 13),
        age=rng.randint(19, 55),
    )
    return fills


CLUSTER_SLOTS: dict[str, Slots] = {
    "bottles": Slots(
        (
            "{e} review after {weeks} weeks",
            "finally caved and got an {e}",
            "is the {e} worth it",
            "my {e} survived a drop onto concrete",
            "switched to {e} and im drinking way more water",
            "which {e} color should i get",
            "{e} vs my old bottle",
            "found an {e} on sale at {store}",
        ),
        (
            "another {e} post... we get it",
            "{e} lid started leaking",
            "unpopular opinion: {e} is overhyped",
            "the {e} craze is officially dead right",
            "returned my {e}",
            "{e} is just a cup",
            "{e} quality dropped?",
            "why does everyone have an {e}",
        ),
        (
            "i was skeptical but the {e} is legit",
            "the {e} is the first bottle that actually made me drink more water",
            "got the {e} as a gift and now i cant use anything else",
            "my {e} has been with me every single day for {weeks} weeks",
            "the {e} lid design is genuinely clever",
            "the {e} keeps ice for like {n}0 hours no joke",
            "the {e} fits in my car cupholder which is all i wanted",
            "bought the {e} for the gym and now its my desk bottle too",
        ),
        (
            "my {e} started leaking from the lid after {weeks} weeks",
            "the {e} feels like a trend thats about to die",
            "the {e} sweats like crazy on my desk",
            "{e} is fine but its a ${price} cup",
            "my sister has {n} {e}s and uses none of them",
            "the {e} handle is awkward to carry",
            "the {e} is overhyped and i said what i said",
            "customer service for the {e} was useless",
        ),
        (
            "mine is the {size} in {color}.",
            "picked it up at {store} for ${price}.",
            "took it on a hike near {city} last {day}.",
            "i refill it {n} times a day at work.",
            "the {color} one was sold out everywhere so i got {color2}.",
            "dropped it off my desk {n} times already.",
            "my partner got the {size} and prefers it.",
            "the straw version was ${price} more at {store}.",
        ),
    ),
    "footwear": Slots(
        (
            "switched to {e} and my knees stopped hurting",
            "{e} worth it for a beginner runner",
            "finally bought {e} after everyone told me to",
            "{e} sizing question",
            "{e} are the most comfortable shoes ive worn",
            "{big} miles on my {e}",
            "{e} on sale at {store}",
            "{e} for standing all day at work?",
        ),
        (
            "am i the only one who doesnt get the {e} hype",
            "{e} fell apart after {n} months",
            "{e} are ugly and i will die on this hill",
            "{e} price went up again",
            "{e} heel slip problem",
            "returned my {e}",
            "{e} quality going downhill?",
            "{e} durability is a joke now",
        ),
        (
            "been running in {e} for {weeks} weeks and my shin splints basically disappeared",
            "my PT recommended {e} and now i own {n} pairs",
            "the cushion on the {e} is unreal",
            "i wear my {e} to work, the gym and the store",
            "the {e} are true to size for me",
            "{big} miles on the {e} and the midsole still feels good",
            "my feet have never been happier than in {e}",
            "{e} look way better in person than in photos",
        ),
        (
            "bought {e} because of the hype and my feet hurt worse",
            "my {e} started squeaking after {n} months",
            "the upper on my {e} tore near the toe",
            "{e} are ${price} now which is wild",
            "the heel slip on the {e} was awful for me",
            "{e} look like clown shoes sorry",
            "my {e} lasted {big} miles before the sole wore flat",
            "the {e} felt mushy and unstable on turns",
        ),
        (
            "went half a size up in the {color} pair.",
            "got them at {store} in {city} for ${price}.",
            "running {n} days a week, mostly {n2}k.",
            "wide fit, {color}, size {shoe}.",
            "my old pair lasted {big} miles for comparison.",
            "tried them on last {day} and bought them on the spot.",
            "the {color2} colorway is sold out online.",
            "i stand {n} hours a day at work for context.",
        ),
    ),
    "beverages": Slots(
        (
            "{e} is the only thing getting me through finals",
            "new {e} flavor is actually good",
            "quit coffee for {e}",
            "{store} has {e} on sale",
            "anyone else drinking way too much {e}",
            "best {e} flavor ranking",
            "{e} converted me",
            "{e} in the gym fridge now",
        ),
        (
            "{e} gave me the worst jitters",
            "is {e} actually healthy or is it marketing",
            "{e} price went up again",
            "{e} tastes like flat soda",
            "{e} is overpriced",
            "sick of seeing {e} everywhere",
            "{e} new flavor is a miss",
            "{e} cans dented again",
        ),
        (
            "the new {e} flavor tastes like candy with zero sugar",
            "i swapped my {n} coffees a day for one {e} and feel better",
            "{e} is winning the fridge war at my office",
            "my gym stocked {e} and i cant stop buying them",
            "{e} got me off regular soda completely",
            "the {flavor} {e} is my daily pick now",
            "{e} is the only drink my whole house agrees on",
            "tried {e} on a whim and now its a case a week",
        ),
        (
            "tried {e} and my heart was pounding for {n} hours",
            "{e} went from ${price} to ${price2} a pack at my gas station",
            "{e} is a soda in a wellness costume",
            "{e} tastes like flat soda to me",
            "the {e} cans are so overpriced",
            "the new {e} flavor tastes like cough syrup",
            "i had {n} {e} in a day and regretted it",
            "{e} marketing is doing a lot of heavy lifting",
        ),
        (
            "{store} has the {n}-pack for ${price} this week.",
            "my favorite is the {flavor} one.",
            "drank {n} of them during finals week.",
            "picked up a case in {city} last {day}.",
            "the {flavor} flavor is sold out at my {store}.",
            "i keep {n} in the fridge at all times.",
            "${price2} a pack at the gas station, ${price} at {store}.",
            "my roommate drinks like {n} a day.",
        ),
    ),
    "beauty": Slots(
        (
            "{e} halo glow is a dupe for the ${price} one",
            "{e} haul everything under $10",
            "{e} power grip primer is unmatched",
            "my {e} products ranked",
            "{e} keeps dropping dupes",
            "is {e} good for sensitive skin",
            "{e} lip oil review",
            "full face of {e} for prom",
        ),
        (
            "{e} quality dropped?",
            "{e} broke me out",
            "{e} not as cheap as it used to be",
            "{e} foundation oxidized on me",
            "{e} releases too many products",
            "{e} concealer creased badly",
            "returned my {e} haul",
            "{e} shade range still bad",
        ),
        (
            "{e} power grip primer replaced my ${price} one and my makeup lasts all day",
            "did a full face of {e} and got so many compliments",
            "spent ${price} at {store} on {e} and got like {n} products",
            "{e} is carrying my entire routine rn",
            "my dermatologist said the {e} moisturizer is formulated well",
            "ran out of my {e} bronzing drops and repurchased immediately",
            "the {e} halo glow is a straight up dupe for the expensive one",
            "{e} camo concealer covers everything for me",
        ),
        (
            "the new {e} foundation oxidized orange on me within an hour",
            "{e} prices keep creeping up",
            "the {e} lip oil was sticky and smelled weird",
            "my {e} concealer creased like crazy",
            "{e} releases a new product every week and half are mid",
            "the {e} primer broke me out after {n} days",
            "{e} packaging broke in my bag again",
            "the {e} blush had zero pigment",
        ),
        (
            "shade {shade}, combo skin, {city} humidity.",
            "got it at {store} for ${price}.",
            "wore it {n} hours last {day} with no touch ups.",
            "i use it with the {color} putty blush.",
            "the {store} near me only had {n} shades left.",
            "i've gone through {n} tubes this year.",
            "tried it over moisturizer and on bare skin.",
            "my sister ({n} years younger) stole mine.",
        ),
    ),
    "costco": Slots(
        (
            "{e} has done it again",
            "the {e} rotisserie chicken is still $4.99",
            "my {e} haul this week",
            "{e} membership is the best money i spend",
            "{e} vs name brand blind taste test",
            "anyone else go to {e} for the vibes",
            "new {e} find",
            "{e} on a weekday morning is peace",
        ),
        (
            "{e} shrinkflation is real",
            "{e} parking lot nearly ended me",
            "they discontinued my favorite {e} item",
            "{e} raised prices again",
            "{e} lines were insane today",
            "{e} quality slipping?",
            "{e} out of stock again",
            "the {e} return line is a nightmare",
        ),
        (
            "{e} won against the name brand in {n2} of {n} categories in our blind test",
            "the {e} membership pays for itself in gas alone",
            "the {e} protein bars are better than quest and half the price",
            "went to {e} for one thing and spent ${big}",
            "{e} on a weekday morning is the most peaceful place on earth",
            "the {e} olive oil is genuinely good",
            "my {e} haul fed the family for {n} weeks",
            "{e} samples alone justify the trip",
        ),
        (
            "the {e} muffin pack went from 12 to 8 and the price went up",
            "went to {e} on a saturday, never again",
            "they discontinued the {e} cookies and i am inconsolable",
            "{e} raised the price on my staples again",
            "the {e} rotisserie chickens have been smaller lately",
            "{e} lines were {n}0 minutes deep today",
            "the {e} parking lot is a war zone",
            "{e} was out of my item for the {n}th week",
        ),
        (
            "the {city} location on {day}.",
            "spent ${big} on {n} items.",
            "the {n}-pack is ${price}.",
            "they moved it to aisle {n} btw.",
            "my membership renews in {month}.",
            "bought {n} of them for the freezer.",
            "the food court hot dog is still $1.50.",
            "the {store} version is ${price2} for comparison.",
        ),
    ),
    "coffee": Slots(
        (
            "{e} opened near me",
            "{e} fall menu is back",
            "{e} rewards hack",
            "my {e} order judge me",
            "{e} is the move for cheap caffeine",
            "the {e} drive thru people are so nice",
            "{e} is my morning now",
            "{e} app finally works",
        ),
        (
            "{e} is too expensive now",
            "{e} messed up my order again",
            "unpopular opinion {e} coffee tastes burnt",
            "the {e} line was {n}0 min this morning",
            "{e} removed my favorite drink",
            "{e} seating is gone",
            "{e} quality fell off",
            "done with {e}",
        ),
        (
            "a {e} opened in my town and the hype is real",
            "the {e} fall drinks slap this year",
            "the {e} rewards stacking saved me like ${price} last month",
            "the {e} drive thru crew remembered my name and my order",
            "{e} is the only place near campus thats cheap and fast",
            "{e} cold brew got me through {n} night shifts",
            "my {e} order is weird but it works",
            "{e} is my little treat {n} days a week",
        ),
        (
            "${price} for a latte at {e} is insane",
            "{e} got my mobile order wrong {n} times this week",
            "{e} coffee tastes burnt to me",
            "waited {n}0 minutes in the {e} drive thru",
            "the {e} near me removed all the seating",
            "{e} dropped my favorite drink from the menu",
            "{e} is understaffed and it shows",
            "the {e} app double charged me",
        ),
        (
            "{city} location, {day} morning.",
            "my order is a {size} iced {flavor} latte.",
            "{n} pumps, oat milk, no foam.",
            "i go about {n} times a week.",
            "stacked the double points with a ${price} gift card.",
            "the one by my office closes at {n}pm now.",
            "parked and walked in instead of the line.",
            "i have {n} free drinks banked.",
        ),
    ),
    "restaurants": Slots(
        (
            "{e} opened near me",
            "{e} > everything else in fast casual",
            "my {e} order hack",
            "{e} is actually worth the price",
            "anyone else obsessed with {e}",
            "took my parents to {e}",
            "{e} new fall bowl",
            "{e} every day this week",
        ),
        (
            "{e} portions are a joke now",
            "{e} charged me ${price} for a bowl",
            "{e} is going downhill",
            "{e} always out of everything",
            "{e} app charged me twice",
            "{e} quality fell off a cliff",
            "{e} rice was crunchy again",
            "done with {e}",
        ),
        (
            "{e} finally opened in my city and the bowls are so good",
            "{e} is replacing my usual lunch spot",
            "the sauces at {e} are elite",
            "{e} for lunch every day this week and no regrets",
            "took my parents to {e} and my dad ordered seconds",
            "the new {e} fall bowl is actually fire",
            "{e} gives double the food for the same price",
            "{e} is {n}00 calories and actually filling",
        ),
        (
            "{e} portions have gotten so small",
            "my {e} bowl was ${price} with a drink",
            "the {e} near me is out of chicken at 1pm every day",
            "{e} quality has fallen off a cliff",
            "the {e} app charged me twice and support ghosted me",
            "the rice at {e} was crunchy again",
            "{e} raised prices and shrank the scoop",
            "waited {n}0 minutes at {e} for a mobile order",
        ),
        (
            "the {city} location on {day}.",
            "my order: {protein}, extra sauce, no onions.",
            "${price} with guac and a drink.",
            "i've been {n} times this month.",
            "they were out of {protein} at {n}pm.",
            "the line was out the door at lunch.",
            "half and half base, ask for it.",
            "coworker got the salad and said the same.",
        ),
    ),
    "apparel": Slots(
        (
            "{e} is actually good now",
            "{e} haul: was skeptical now a convert",
            "{e} sale is live",
            "finally tried {e}",
            "{e} quality check after a year",
            "best {e} basics for fall",
            "{e} jeans fit review",
            "{e} jacket survived the rain",
        ),
        (
            "{e} quality has gone downhill",
            "{e} prices are out of control",
            "{e} isnt cool anymore",
            "my {e} leggings pilled",
            "{e} sizing is all over the place",
            "{e} stores are empty",
            "{e} fell apart in {n} months",
            "{e} designs are stale",
        ),
        (
            "{e} rebranded and the clothes are actually good now",
            "went into {e} on a whim and left with ${big} of stuff",
            "{e} basics are the backbone of my wardrobe",
            "{e} quality is still the best for workout stuff",
            "found {e} sweaters on sale for ${price} and bought {n} colors",
            "wore the {e} jacket through a rainy fall and its perfect",
            "the {e} jeans fit better than anything else ive tried",
            "my {n} year old {e} pair still looks new",
        ),
        (
            "{e} leggings pilled after {n} washes",
            "nobody at my school wears {e} anymore",
            "{e} raised prices again with the same recycled designs",
            "my {e} shoes fell apart in {n} months",
            "{e} stores are empty every time i go",
            "{e} sizing changed and nothing fits now",
            "the {e} fabric feels cheaper than last year",
            "{e} is coasting on the name",
        ),
        (
            "size {size}, {color}, from the {city} store.",
            "${price} on sale from ${price2}.",
            "washed it {n} times, cold, hung dry.",
            "bought it last {day} at {store}.",
            "the {color2} one is sold out online.",
            "i'm 5'{n2} for reference.",
            "had the old version for {n} years.",
            "fit pic in comments.",
        ),
    ),
    "gadgets": Slots(
        (
            "{e} worth it in 2026",
            "got the {e} and my sleep improved",
            "{e} {n} month review",
            "{e} on sale, pull the trigger?",
            "the {e} readiness score is scarily accurate",
            "my {e} saved my morning run",
            "{e} battery still great",
            "{e} finally clicked for me",
        ),
        (
            "{e} subscription is a scam",
            "{e} battery dying after a year",
            "{e} is overpriced",
            "lost one {e} again",
            "{e} app is a mess",
            "{e} readiness score is nonsense",
            "{e} replacement cost is insane",
            "returned my {e}",
        ),
        (
            "the {e} told me i was getting sick {n} days before i felt it",
            "{e} on sale for ${price} at {store} and i grabbed them",
            "{weeks} weeks with the {e} and i actually changed my habits",
            "the {e} transparency mode is so good i forget they're in",
            "the {e} made me actually care about sleep",
            "{e} battery still holds up after a year",
            "the {e} fit is perfect for running",
            "{e} pairing is instant and never fails",
        ),
        (
            "${n} a month subscription for the {e} on top of the hardware is a no",
            "my {e} battery went from {n} hours to {n2}0 minutes",
            "the {e} is a ${big} pedometer with an app",
            "{e} said i was optimal after {n2} hours of sleep",
            "lost one {e} and the replacement is ${price}",
            "the {e} app crashes every other day",
            "{e} readiness is basically random for me",
            "the {e} case hinge broke in {n} months",
        ),
        (
            "size {n}, {color}, left hand.",
            "paired with an iphone, firmware {n}.{n2}.",
            "bought at {store} for ${price}.",
            "wore it on a {n}k run last {day}.",
            "my sleep went from {n2} to {n} hours avg.",
            "charging once every {n} days.",
            "{store} had {n} left in stock.",
            "i track {n} workouts a week with it.",
        ),
    ),
    "gaming": Slots(
        (
            "{e} day one releases this month are stacked",
            "{e} is still the best deal in gaming",
            "{e} got me into indie games",
            "finished {n} games on {e} this month",
            "{e} cloud on my laptop is good",
            "{e} saved me ${big} this year",
            "{e} new additions",
            "{e} worth it for pc?",
        ),
        (
            "{e} price hike is the last straw",
            "cancelled my {e} today",
            "{e} removing games again",
            "is {e} even worth it anymore",
            "{e} ultimate is ${price} a month now",
            "{e} auto renewed at the new price",
            "{e} quality dropping",
            "done with {e}",
        ),
        (
            "the {e} day one lineup this month is nuts",
            "{e} got me playing indie stuff i'd never buy",
            "{e} is still the best deal in gaming even after the hike",
            "finished {n} games on {e} this month",
            "{e} cloud streaming on my laptop is shockingly good",
            "{e} saved me like ${big} this year",
            "{e} is the only subscription i never cancel",
            "{e} quests paid for {n} months of my sub",
        ),
        (
            "{e} went up again, {n2} price hikes in 2 years",
            "the {e} price hike pushed me over the edge",
            "{e} removed {n} games i was in the middle of",
            "{e} at ${price} a month is more than netflix",
            "{e} used to be an insane deal, now its just expensive",
            "my {e} auto renewed at the new price without telling me",
            "the {e} lineup has been dry for {n} months",
            "{e} cloud lag made it unplayable for me",
        ),
        (
            "playing on series x and a {n} year old laptop.",
            "cancelled on {day}, renews in {month}.",
            "i was paying ${price2}, now ${price}.",
            "{n} games in my backlog.",
            "my kid plays {n} hours a week on it.",
            "switched to the ${price2} tier.",
            "bought {n} games on sale instead.",
            "steam sale had the same games for ${price}.",
        ),
    ),
    "grocery": Slots(
        (
            "new {e} finds this week",
            "{e} fall items ranked",
            "{e} is the only grocery store with a soul",
            "the {e} crew is unreasonably nice",
            "whats your {e} must buy",
            "{e} frozen section carries my meal prep",
            "{e} haul under ${price}",
            "{e} snack tier list",
        ),
        (
            "{e} discontinued my favorite thing again",
            "{e} parking lot is a crime",
            "{e} shrinkflation spotted",
            "{e} produce goes bad in 2 days",
            "{e} out of everything again",
            "{e} prices creeping up",
            "{e} recall again",
            "{e} lines on {day}",
        ),
        (
            "the {e} pumpkin bread mix is back and its 10/10",
            "the {e} cashier gave me flowers because it was slow",
            "{e} frozen section is my whole meal prep",
            "the {e} chili onion crunch changed my life",
            "{e} is the only place i leave happy and under ${price}",
            "{e} fall items are better than last year",
            "the {e} crew remembered my name",
            "{e} snacks carried my road trip",
        ),
        (
            "{e} discontinued the mango chunks again",
            "the {e} parking lot was designed by someone who hates people",
            "{e} shrinkflation: the cookie butter jar is smaller",
            "{e} was sold out of everything at 10am",
            "{e} produce goes bad in {n2} days",
            "{e} prices crept up ${n} on my usual haul",
            "{e} recalled my favorite frozen item",
            "the {e} line was {n}0 deep on a {day}",
        ),
        (
            "{city} store, {day} morning.",
            "spent ${price} on {n} items.",
            "the {flavor} one is the move.",
            "bought {n} for the freezer.",
            "they moved it to the end cap.",
            "my usual haul is ${price}.",
            "the {store} version isnt as good.",
            "tried it {n} ways this week.",
        ),
    ),
    "ev": Slots(
        (
            "{n2} years with my {e}",
            "{e} road trip update",
            "{e} fsd drove me to work",
            "switched to a {e} and my gas budget disappeared",
            "{e} charging costs breakdown",
            "{e} battery degradation after {big}k miles",
            "{e} in winter report",
            "{e} camping mode is underrated",
        ),
        (
            "{e} service center took {n} weeks",
            "my {e} panel gaps",
            "{e} insurance quote made me gasp",
            "{e} build quality anyone",
            "another {e} recall",
            "{e} wipers still cant handle rain",
            "{e} phantom braking again",
            "getting flipped off in my {e}",
        ),
        (
            "charging my {e} at home is ${price} a month vs ${big} in gas",
            "did a {big}0 mile road trip in the {e} with zero range anxiety",
            "{e} fsd drove me {n}0 minutes to work with zero interventions",
            "the {e} is boring but its the best appliance ive owned",
            "{e} battery degradation after {big}k miles is {n2}%",
            "the {e} camping mode made my trip",
            "my {e} handles snow better than my old suv",
            "the {e} app preheating the car is life changing",
        ),
        (
            "my {e} door handle broke and service had a {n} week wait",
            "{e} panel gaps on my new car are visible from space",
            "{e} insurance quote was ${big} a month",
            "the {e} wipers still cant figure out rain",
            "{e} recall notice again",
            "the {e} brand got so political i get flipped off",
            "{e} phantom braked on the highway twice today",
            "the {e} service center ghosted me for {n} days",
        ),
        (
            "2024 long range, {color}.",
            "{big}k miles, {city} area.",
            "superchargers were ${price} per session.",
            "{n2} kids and a dog in the back.",
            "home charger on a 240v outlet.",
            "winter range is about {big} miles.",
            "software version {n}.{n2}.",
            "traded in a {n} year old suv.",
        ),
    ),
}
# GameStop posts are 100% stock talk, so the cluster never reaches the consumer slots.
CLUSTER_SLOTS["stock"] = CLUSTER_SLOTS["ev"]

STOCK_SLOTS = Slots(
    (
        "{e} earnings play",
        "loaded up on {e} calls",
        "{e} is about to rip",
        "{e} short interest is insane",
        "sold my {e} puts for a {big}% gain",
        "why is {e} up {n}% today",
        "{e} DD",
        "{e} yolo update",
        "{e} covered calls strategy",
        "bagholding {e} since 2021",
    ),
    (),
    (
        "{e} earnings next week and iv is through the roof",
        "put my paycheck into {e} 0dte calls",
        "{e} short interest is {big}%",
        "sold cash secured puts on {e} at the {big} strike",
        "{e} revenue flat but the cash pile is growing",
        "{e} calls down {big}% and im holding till expiry",
        "{e} up {n}% on no news",
        "{e} is the ultimate meme, flow matters not fundamentals",
        "been wheeling {e} for {n} months",
        "{e} chart is forming a cup and handle",
    ),
    (),
    (
        "{n} contracts, {month} expiry.",
        "avg cost ${price}.",
        "position is {n}% of my port.",
        "bought in last {day} at open.",
        "iv rank is {big}.",
        "{n}0 delta, {n2} weeks out.",
        "theta is eating me alive.",
        "not financial advice. its financial advice.",
    ),
)
SIGNOFF_STOCK = (
    "positions or ban, i know.",
    "dont follow me into this.",
    "see you on the moon or in the wendys dumpster.",
    "thoughts?",
    "am i cooked?",
    "roast me.",
    "updates after close.",
    "this is the way.",
)

GENERIC_TITLES = (
    "what's your morning routine",
    "anyone else struggling to stay consistent this month",
    "weekly check in thread",
    "unpopular opinion thread",
    "what's one purchase that actually changed your life",
    "rant: why is everything so expensive now",
    "first post here, be nice",
    "how do you guys stay motivated",
    "the fall weather has me in a good mood",
    "need recs, budget is tight",
    "daily discussion thread",
    "does anyone actually use the stuff they buy",
)
GENERIC_EXP = (
    "my morning routine is coffee, dog walk, work, repeat",
    "motivation has been low this month",
    "weekly check in: hit my goals {n2} of 7 days",
    "most of the stuff in this sub is just advertising",
    "lurker here, you all have helped me a ton",
    "everything costs {big}% more and my salary went up {n}%",
    "i just want to complain for a minute",
    "walked outside and it smelled like fall",
    "whats the one thing you bought that you still use a year later",
    "stayed off my phone for a weekend and im weirdly calm",
    "what are you all working on today",
    "i just like reading this sub without buying anything",
)
GENERIC_DETAIL = (
    "{city}, {n} years into this hobby.",
    "been here since {month}.",
    "budget is about ${price} a month.",
    "{n2} kids, full time job, no time.",
    "i'm {age} if that matters.",
    "started last {month}.",
    "posting from {city} on my lunch break.",
    "this is my {n}th attempt lol.",
)

CO_MENTION_POS = (
    " also tried {e2} last week and honestly pretty solid too.",
    " (for context i also have {e2} and like both)",
    " edit: a few people asked, yes i've also used {e2}, also good.",
)
CO_MENTION_NEG = (
    " tried {e2} too and it was worse tbh.",
    " (not switching to {e2} either, that one's mid)",
    " edit: no i will not be trying {e2}, stop asking lol",
)

SPAM_TITLES = (
    "Olipop is a game changer!!",
    "olipop is a game changer!",
    "OLIPOP is a game changer!!!",
    "Olipop is a total game changer",
)
SPAM_BODY = (
    "Just discovered Olipop and WOW the prebiotic soda that actually tastes good! "
    "Use my code SODA20 for 20% off at drinkolipop.com #ad"
)
SPAM_VARIANTS = (
    ("Just", "just"),
    ("WOW", "wow"),
    ("WOW", "WOW!!"),
    ("#ad", "#sponsored"),
    ("#ad", ""),
    ("20% off", "20 % off"),
    ("tastes good!", "tastes good"),
    ("actually", "actualy"),
)

NEWS_SOURCES = (
    ("Yahoo Finance", "finance.yahoo.com"),
    ("Reuters", "www.reuters.com"),
    ("CNBC", "www.cnbc.com"),
    ("Bloomberg", "www.bloomberg.com"),
    ("MarketWatch", "www.marketwatch.com"),
    ("Barron's", "www.barrons.com"),
    ("Business Insider", "www.businessinsider.com"),
    ("Retail Dive", "www.retaildive.com"),
    ("Modern Retail", "www.modernretail.co"),
    ("Fast Company", "www.fastcompany.com"),
)
NEWS_GENERIC_PUBLIC = (
    "{parent} shares {dir} {pct}% after {q} results",
    "Analysts weigh in on {parent} ahead of {q} earnings",
    "{parent} ({ticker}) stock: what Wall Street is watching this week",
    "Is {parent} stock a buy after its latest move?",
    "{parent} price target raised at {bank}",
    "{parent} price target cut at {bank} on margin concerns",
    "Why {parent} stock {dir2} today",
    "{parent} to report {q} earnings: here's what to expect",
    "{parent} insiders sell shares after rally",
    "Options traders bet on big move in {parent} ({ticker})",
)
NEWS_GENERIC_PRIVATE = (
    "{parent} reportedly explores new funding round",
    "{parent} expands distribution to new retailers",
    "Inside {parent}'s growth strategy",
    "{parent} names new chief marketing officer",
    "How {parent} is winning over Gen Z shoppers",
)
BANKS = (
    "Goldman Sachs",
    "Morgan Stanley",
    "JPMorgan",
    "Piper Sandler",
    "Stifel",
    "UBS",
    "Jefferies",
)
QUARTERS = ("Q2", "Q3", "fiscal Q1", "third-quarter", "second-quarter")


# --------------------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------------------
def poisson(rng, lam: float) -> int:
    """Knuth's algorithm; fine for the small rates used here."""
    if lam <= 0:
        return 0
    limit = math.exp(-lam)
    k, p = 0, 1.0
    while True:
        p *= rng.random()
        if p <= limit:
            return k
        k += 1


def noisy_count(rng, lam: float) -> int:
    """Poisson-ish daily count with the deviation damped to 60% so the designed shapes stay
    legible over a 7-day window (a pure Poisson week can drift a 'flat' entity by 30%+)."""
    return max(0, round(lam + 0.6 * (poisson(rng, lam) - lam)))


def day_at(i: int) -> date:
    return START_DAY + timedelta(days=i)


def iso_at(rng, d: date) -> str:
    hour = rng.choices(range(24), weights=HOUR_WEIGHTS)[0]
    return datetime(d.year, d.month, d.day, hour, rng.randrange(60), tzinfo=UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )


def daily_rate(spec: EntitySpec, day_index: int, scale: float) -> float:
    """Baseline mean for the first 8 weeks; in the last week ramp around the recent mean so
    the weekly average lands on ``recent_rate`` while still trending within the week."""
    if day_index < BASELINE_DAYS:
        return spec.base_rate * scale
    i = day_index - BASELINE_DAYS  # 0..6
    ramp = 0.85 + 0.30 * i / (RECENT_DAYS - 1)
    return spec.recent_rate * ramp * scale


def sentiment_at(rng, spec: EntitySpec, day_index: int, stock: bool) -> float:
    mean = spec.sent_start + (spec.sent_end - spec.sent_start) * day_index / (N_DAYS - 1)
    s = mean + rng.gauss(0, 0.35 if stock else 0.25)
    return round(max(-1.0, min(1.0, s)), 1) + 0.0  # + 0.0 turns -0.0 into 0.0


def sample_score(rng, bot: bool = False) -> int:
    if bot:
        return max(0, int(rng.lognormvariate(0.7, 0.9)))
    if rng.random() < 0.03:  # viral tail
        return min(4000, int(rng.lognormvariate(math.log(500), 1.1)))
    return int(rng.lognormvariate(math.log(12), 1.25))


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:70]


# --------------------------------------------------------------------------------------
# Authors
# --------------------------------------------------------------------------------------
@dataclass(frozen=True)
class Author:
    author_id: str
    karma: int
    age_days: int
    is_bot: bool


def make_authors(rng) -> tuple[list[Author], list[Author], list[Author], Author]:
    """Returns (normal, bots, spam_campaign, prolific) author pools."""
    normal: list[Author] = []
    for i in range(1, N_AUTHORS + 1):
        karma = int(min(50_000, max(60, rng.lognormvariate(math.log(900), 1.5))))
        age = int(60 + 3940 * rng.betavariate(1.3, 1.0))
        normal.append(Author(f"u_{i:04d}", karma, age, False))
    bots = [
        Author(f"u_{N_AUTHORS + i:04d}", rng.randint(1, 49), rng.randint(1, 29), True)
        for i in range(1, N_BOT_AUTHORS + 1)
    ]
    spam = [
        Author(
            f"u_{N_AUTHORS + N_BOT_AUTHORS + i:04d}", rng.randint(1, 20), rng.randint(1, 12), True
        )
        for i in range(1, 6)
    ]
    prolific = normal[41]  # u_0042: an ordinary, established account that over-posts about Owala
    return normal, bots, spam, prolific


# --------------------------------------------------------------------------------------
# Reddit posts
# --------------------------------------------------------------------------------------
def entity_record(name: str, sentiment: float, purchase: bool, stock_talk: bool) -> dict[str, Any]:
    return {
        "name": name,
        "type": ENTITY_BY_NAME[name].etype,
        "sentiment": sentiment,
        "is_purchase_intent": purchase,
        "is_stock_talk": stock_talk,
    }


def compose_title(rng, leads: tuple[str, ...], fills: dict[str, Any]) -> str:
    return rng.choice(leads).format_map(fills) + rng.choice(TITLE_TAILS)


def compose_body(
    rng,
    exp: tuple[str, ...],
    detail: tuple[str, ...],
    signoffs: tuple[str, ...],
    fills: dict[str, Any],
) -> str:
    """3-5 slots: [opener] experience. detail. [detail.] [sign-off]."""
    parts: list[str] = []
    if rng.random() < 0.7:
        parts.append(rng.choice(OPENERS))
    parts.append(rng.choice(exp).format_map(fills) + rng.choice((".", "!", "...", "")))
    details = rng.sample(detail, 2 if rng.random() < 0.4 else 1)
    parts.extend(d.format_map(fills) for d in details)
    if rng.random() < 0.7:
        parts.append(rng.choice(signoffs))
    return " ".join(parts)


def sprinkle(rng, text: str, protected: str) -> str:
    """Random casing/typo/emoji noise. Words of the entity alias are never touched."""
    words = text.split(" ")
    keep = {w.lower() for w in protected.split()}
    candidates = [
        i for i, w in enumerate(words) if len(w) > 3 and w.isalpha() and w.lower() not in keep
    ]
    if candidates and rng.random() < 0.12:  # typo: swap two adjacent letters or drop one
        i = rng.choice(candidates)
        w = words[i]
        k = rng.randrange(1, len(w) - 1)
        words[i] = (
            w[:k] + w[k + 1] + w[k] + w[k + 2 :] if rng.random() < 0.5 else w[:k] + w[k + 1 :]
        )
    if candidates and rng.random() < 0.08:  # one SHOUTED word
        i = rng.choice(candidates)
        words[i] = words[i].upper()
    if rng.random() < 0.15:
        words[0] = words[0][:1].upper() + words[0][1:]
    if rng.random() < 0.1:
        i = rng.randrange(1, len(words))
        words[i] = words[i] + rng.choice(INTERJECTIONS)
    text = " ".join(words)
    if rng.random() < 0.1:
        text += " " + rng.choice(EMOJIS)
    return text


def build_entity_post(
    rng,
    spec: EntitySpec,
    day_index: int,
    author: Author,
    scale: float,
) -> dict[str, Any]:
    stock = rng.random() < spec.stock_frac
    sentiment = sentiment_at(rng, spec, day_index, stock)
    fills = make_fills(rng)
    if stock:
        # Entities whose own sub list is all stock subs (GameStop) stay inside that list.
        sub = rng.choice(spec.subs if all(s in STOCK_SUBS for s in spec.subs) else STOCK_SUBS)
        alias = rng.choice(spec.stock_aliases)
        fills["e"] = alias
        title = compose_title(rng, STOCK_SLOTS.title_pos, fills)
        body = compose_body(rng, STOCK_SLOTS.exp_pos, STOCK_SLOTS.detail, SIGNOFF_STOCK, fills)
        purchase = False
    else:
        sub = rng.choice(spec.subs)
        alias = rng.choice(spec.aliases)
        fills["e"] = alias
        slots = CLUSTER_SLOTS[spec.cluster]
        if sentiment >= 0.15:
            positive = True
        elif sentiment <= -0.15:
            positive = False
        else:
            positive = rng.random() < 0.5
        title = compose_title(rng, slots.title_pos if positive else slots.title_neg, fills)
        body = compose_body(
            rng,
            slots.exp_pos if positive else slots.exp_neg,
            slots.detail,
            SIGNOFF_POS if positive else SIGNOFF_NEG,
            fills,
        )
        purchase = positive and rng.random() < spec.purchase_p
    body = sprinkle(rng, body, alias)

    entities = [entity_record(spec.name, sentiment, purchase, stock)]
    if not stock and rng.random() < CO_MENTION_P and spec.name in CO_MENTIONS:
        other = ENTITY_BY_NAME[rng.choice(CO_MENTIONS[spec.name])]
        other_sent = sentiment_at(rng, other, day_index, False)
        tmpl = CO_MENTION_POS if other_sent >= 0 else CO_MENTION_NEG
        body += rng.choice(tmpl).format(e2=rng.choice(other.aliases))
        entities.append(entity_record(other.name, other_sent, False, False))

    return finish_post(rng, sub, author, day_at(day_index), title, body, entities, author.is_bot)


def finish_post(
    rng,
    sub: str,
    author: Author,
    d: date,
    title: str,
    body: str,
    entities: list[dict[str, Any]],
    bot: bool,
    score: int | None = None,
) -> dict[str, Any]:
    return {
        "id": "",  # assigned after chronological sort
        "source": "reddit",
        "subreddit": sub,
        "author_id": author.author_id,
        "author_karma": author.karma,
        "author_age_days": author.age_days,
        "created_at": iso_at(rng, d),
        "score": sample_score(rng, bot) if score is None else score,
        "title": title,
        "body": body,
        "url": "",
        "is_stock_sub": sub in STOCK_SUBS,
        "entities": entities,
    }


def build_generic_post(rng, author: Author, day_index: int) -> dict[str, Any]:
    sub = rng.choice(CONSUMER_SUBS if rng.random() < 0.85 else STOCK_SUBS)
    fills = make_fills(rng)
    title = compose_title(rng, GENERIC_TITLES, fills)
    body = sprinkle(
        rng, compose_body(rng, GENERIC_EXP, GENERIC_DETAIL, SIGNOFF_POS + SIGNOFF_NEG, fills), ""
    )
    return finish_post(rng, sub, author, day_at(day_index), title, body, [], author.is_bot)


def build_spam_campaign(rng, spam_authors: list[Author]) -> list[dict[str, Any]]:
    posts = []
    for _ in range(SPAM_CAMPAIGN_POSTS):
        body = SPAM_BODY
        for old, new in rng.sample(SPAM_VARIANTS, rng.randint(0, 2)):
            body = body.replace(old, new, 1)
        author = rng.choice(spam_authors)
        day_index = BASELINE_DAYS + rng.randrange(RECENT_DAYS)
        posts.append(
            finish_post(
                rng,
                rng.choice(("energydrinks", "Frugal", "Fitness", "teenagers")),
                author,
                day_at(day_index),
                rng.choice(SPAM_TITLES),
                body,
                [entity_record("Olipop", 0.9, True, False)],
                True,
                score=rng.randint(0, 4),
            )
        )
    return posts


def pick_author(rng, normal: list[Author], weights: list[float], bots: list[Author]) -> Author:
    if rng.random() < BOT_POST_FRACTION:
        return rng.choice(bots)
    return rng.choices(normal, weights=weights)[0]


def generate_posts(rng, scale: float) -> tuple[list[dict[str, Any]], dict[str, int]]:
    normal, bots, spam_authors, prolific = make_authors(rng)
    weights = [1.0 / (i + 1) ** 0.6 for i in range(len(normal))]  # Zipf-ish: a few heavy posters
    posts: list[dict[str, Any]] = []
    owala_recent: list[dict[str, Any]] = []

    for spec in ENTITIES:
        # Baseline weeks: damped Poisson per day. Recent week: the weekly total is pinned to
        # recent_rate * 7 so the shape tests see the designed last-week average even at small
        # scales; the posts are spread over the 7 days following the within-week ramp.
        counts = [noisy_count(rng, daily_rate(spec, d, scale)) for d in range(BASELINE_DAYS)]
        recent_days = list(range(BASELINE_DAYS, N_DAYS))
        ramp = [daily_rate(spec, d, scale) for d in recent_days]
        counts += [0] * RECENT_DAYS
        for d in rng.choices(
            recent_days, weights=ramp, k=round(spec.recent_rate * RECENT_DAYS * scale)
        ):
            counts[d] += 1
        for day_index, n_posts in enumerate(counts):
            for _ in range(n_posts):
                author = pick_author(rng, normal, weights, bots)
                post = build_entity_post(rng, spec, day_index, author, scale)
                posts.append(post)
                if spec.name == "Owala" and day_index >= BASELINE_DAYS:
                    owala_recent.append(post)

    # Author-cap test: one established account posts ~25 of the last-week Owala posts.
    rng.shuffle(owala_recent)
    for post in owala_recent[:PROLIFIC_OWALA_POSTS]:
        post["author_id"], post["author_karma"], post["author_age_days"] = (
            prolific.author_id,
            prolific.karma,
            prolific.age_days,
        )
    prolific_count = min(PROLIFIC_OWALA_POSTS, len(owala_recent))

    # Generic chatter with no brand: ~12% of the final corpus.
    n_generic = round(len(posts) * EMPTY_ENTITY_FRACTION / (1 - EMPTY_ENTITY_FRACTION))
    for _ in range(n_generic):
        author = pick_author(rng, normal, weights, bots)
        posts.append(build_generic_post(rng, author, rng.randrange(N_DAYS)))

    spam_posts = build_spam_campaign(rng, spam_authors)
    posts.extend(spam_posts)

    posts.sort(key=lambda p: (p["created_at"], p["subreddit"], p["title"]))
    for n, post in enumerate(posts, start=1):
        post["id"] = f"fx-{n:06d}"
        post["url"] = f"https://reddit.com/r/{post['subreddit']}/comments/fx{n:06d}"

    stats = {
        "bot_posts": sum(1 for p in posts if p["author_age_days"] < 30 and p["author_karma"] < 50),
        "spam_campaign_posts": len(spam_posts),
        "prolific_owala_posts": prolific_count,
        "generic_posts": n_generic,
        "authors": len({p["author_id"] for p in posts}),
    }
    return posts, stats


# --------------------------------------------------------------------------------------
# Pageviews
# --------------------------------------------------------------------------------------
def generate_pageviews(rng) -> dict[str, list[dict[str, Any]]]:
    out: dict[str, list[dict[str, Any]]] = {}
    for spec in ENTITIES:
        series = []
        for i in range(N_DAYS):
            d = day_at(i)
            weekday_factor = 0.9 if d.weekday() >= 5 else 1.0
            if i < BASELINE_DAYS:
                trend = 1.0
            else:
                trend = 1.0 + (spec.pv_mult - 1.0) * (i - BASELINE_DAYS + 1) / RECENT_DAYS
            noise = rng.gauss(1.0, 0.08)
            series.append(
                {
                    "day": d.isoformat(),
                    "count": max(50, int(spec.pv_base * weekday_factor * trend * noise)),
                }
            )
        out[spec.wiki] = series
    return out


# --------------------------------------------------------------------------------------
# News
# --------------------------------------------------------------------------------------
def headline_for(rng, spec: EntitySpec) -> str:
    pool = list(spec.headlines)
    pool.extend(NEWS_GENERIC_PUBLIC if spec.ticker else NEWS_GENERIC_PRIVATE)
    tmpl = rng.choice(pool)
    return tmpl.format(
        parent=spec.parent,
        ticker=spec.ticker or "",
        q=rng.choice(QUARTERS),
        pct=rng.choice((2, 3, 4, 5, 6, 8, 11, 14)),
        dir=rng.choice(("rise", "fall", "jump", "slide")),
        dir2=rng.choice(("is rising", "is falling", "jumped", "dropped")),
        bank=rng.choice(BANKS),
    )


def generate_news(rng) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for spec in ENTITIES:
        for i in range(N_DAYS):
            rate = spec.news_base if i < BASELINE_DAYS else spec.news_recent
            for _ in range(poisson(rng, rate)):
                src, domain = rng.choice(NEWS_SOURCES)
                title = headline_for(rng, spec)
                d = day_at(i)
                published = datetime(
                    d.year,
                    d.month,
                    d.day,
                    rng.randint(6, 22),
                    rng.randrange(60),
                    tzinfo=UTC,
                )
                items.append(
                    {
                        "id": "",
                        "title": title,
                        "published_at": published.strftime("%Y-%m-%dT%H:%M:%SZ"),
                        "source": src,
                        "url": f"https://{domain}/news/{slugify(title)}",
                        "query": spec.name,
                    }
                )
    items.sort(key=lambda x: (x["published_at"], x["query"], x["title"]))
    for n, item in enumerate(items, start=1):
        item["id"] = f"nw-{n:06d}"
        item["url"] = f"{item['url']}-{n:06d}"
    return items


# --------------------------------------------------------------------------------------
# README + stats
# --------------------------------------------------------------------------------------
TOKEN_RE = re.compile(r"[a-z0-9$']+")


def shingles(text: str) -> frozenset[tuple[str, ...]]:
    toks = TOKEN_RE.findall(text.lower())
    return frozenset(tuple(toks[i : i + 3]) for i in range(len(toks) - 2))


def near_duplicate_rate(posts: list[dict[str, Any]], threshold: float = 0.8) -> tuple[int, int]:
    """Greedy chronological dedupe on title+body 3-shingles; returns (dupes, considered).

    Campaign posts are excluded (they are near-duplicates by design). Uses prefix filtering:
    two sets with Jaccard >= t must share a shingle among their rarest |s| - ceil(t|s|) + 1
    shingles under a global ordering, so only those are indexed/probed, then verified exactly.
    """
    texts = [p["title"] + " " + p["body"] for p in posts if "SODA20" not in p["body"]]
    sets = [shingles(t) for t in texts]
    freq: Counter[tuple[str, ...]] = Counter(s for st in sets for s in st)
    index: dict[tuple[str, ...], list[int]] = defaultdict(list)
    kept: list[frozenset[tuple[str, ...]]] = []
    dupes = 0
    for st in sets:
        if not st:
            kept.append(st)
            continue
        ordered = sorted(st, key=lambda s: (freq[s], s))
        prefix = ordered[: len(st) - math.ceil(threshold * len(st)) + 1]
        candidates = {j for s in prefix for j in index[s]}
        is_dupe = False
        for j in candidates:
            other = kept[j]
            inter = len(st & other)
            if inter / (len(st) + len(other) - inter) >= threshold:
                is_dupe = True
                break
        if is_dupe:
            dupes += 1
            kept.append(frozenset())
            continue
        for s in prefix:
            index[s].append(len(kept))
        kept.append(st)
    return dupes, len(sets)


def mention_table(posts: list[dict[str, Any]]) -> dict[str, tuple[float, float]]:
    """Per-entity (baseline mean/day, last-week mean/day) counting every entity mention."""
    recent_start = day_at(BASELINE_DAYS).isoformat()
    base: Counter[str] = Counter()
    recent: Counter[str] = Counter()
    for p in posts:
        bucket = recent if p["created_at"][:10] >= recent_start else base
        for ent in p["entities"]:
            bucket[ent["name"]] += 1
    return {e.name: (base[e.name] / BASELINE_DAYS, recent[e.name] / RECENT_DAYS) for e in ENTITIES}


def write_readme(
    path: Path,
    posts: list[dict[str, Any]],
    news: list[dict[str, Any]],
    stats: dict[str, int],
    scale: float,
) -> None:
    table = mention_table(posts)
    news_counts = Counter(n["query"] for n in news)
    lines = [
        "# Consumer-trend fixture corpus",
        "",
        f"Generated by `scripts/gen_social_fixtures.py` (seed {SEED}, scale {scale}). Deterministic; regenerate",
        "with `.venv/bin/python scripts/gen_social_fixtures.py` rather than editing by hand.",
        "",
        f"Window: {START_DAY.isoformat()} .. {day_at(N_DAYS - 1).isoformat()} ({N_DAYS} days = {BASELINE_DAYS // 7} baseline weeks",
        f"+ the 'recent' week {day_at(BASELINE_DAYS).isoformat()} .. {day_at(N_DAYS - 1).isoformat()}).",
        "",
        "## Files",
        "",
        "- `reddit_posts.jsonl` - one post per line. `entities` is the GROUND-TRUTH extraction the offline",
        "  fixture LLM replays (type in product|brand|company|store, sentiment in [-1, 1], one decimal).",
        f"  {len(posts)} posts, {stats['authors']} authors, ~{EMPTY_ENTITY_FRACTION:.0%} with empty `entities`.",
        "- `pageviews.json` - Wikipedia article title -> 63 daily `{day, count}` entries.",
        f"- `news_items.jsonl` - {len(news)} financial headlines; `query` is the canonical entity name.",
        "",
        "## Adversarial cases the filters must handle",
        "",
        f"- **Bot/spam accounts**: {stats['bot_posts']} posts come from accounts with `author_age_days < 30` and",
        "  `author_karma < 50` (~3% of organic posts plus the campaign below). Drop them.",
        f'- **Olipop spam campaign**: {stats["spam_campaign_posts"]} near-duplicate posts ("Just discovered Olipop and WOW...',
        '  code SODA20") from 5 fresh accounts in the last 7 days. Dedupe should collapse them to ~1.',
        f"- **Author cap**: `u_0042` posts {stats['prolific_owala_posts']} times about Owala in the last week. Per-author",
        "  caps should keep Owala's breakout intact but not let one account drive it.",
        f"- **Lexical diversity**: ordinary posts are composed from slots, so only {stats['near_dupes']} of",
        f"  {stats['dedupe_considered']} non-campaign posts ({stats['near_dupes'] / stats['dedupe_considered']:.1%}) are near-duplicates",
        "  of an earlier post (title+body, lowercase `[a-z0-9$']+` tokens, 3-word shingles, Jaccard >= 0.8, greedy",
        "  chronological). A dedupe filter should remove the campaign, not the corpus.",
        "- **Stock-sub hype**: GameStop appears only in wallstreetbets/stocks/options with `is_stock_talk=true`;",
        "  70% of Tesla posts are the same. Stock talk is not consumer demand and must be penalised.",
        "- **Aliases/misspellings**: hokas, elf, lulu, sbux, birks, TJ's, gamepass, etc. The ground truth",
        "  always uses the canonical name.",
        "",
        "## Designed trend shapes",
        "",
        "Realised mentions/day count every entity mention (primary + co-mentions), so numbers sit a little",
        "above the design rate. Sentiment is the per-post mean at window start -> end.",
        "",
        "| Entity | Type | Design (base -> recent /day) | Realised base | Realised recent | Sentiment | News items | Pageviews x | Designed outcome |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for e in ENTITIES:
        b, r = table[e.name]
        lines.append(
            f"| {e.name} | {e.etype} | {e.base_rate:g} -> {e.recent_rate:g} | {b:.1f} | {r:.1f} | "
            f"{e.sent_start:+.1f} -> {e.sent_end:+.1f} | {news_counts[e.name]} | {e.pv_mult:g} | {e.outcome} |"
        )
    lines += [
        "",
        "## Expected ranking (rough)",
        "",
        "- **Should score high**: Owala, CAVA (breakout + news coverage gap), HOKA, then Crocs, e.l.f., Dutch Bros, Abercrombie.",
        "- **Signal but not investable**: Oura Ring, Olipop, Trader Joe's, Liquid Death (private); Uniqlo (Tokyo-listed);",
        "  Owala/Stanley (private parents) surface as signals only.",
        "- **Should score low**: Celsius (hot all window, saturated news -> no novelty), Stanley Quencher (fading, sarcastic),",
        "  Starbucks (declining, negative), Nike/Chipotle (flat, negative), Lululemon/Sweetgreen (flat, neutral).",
        "- **Must be penalised as hype**: GameStop (100% stock talk), Tesla (70% stock talk, saturated coverage).",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")


def print_stats(
    posts: list[dict[str, Any]], news: list[dict[str, Any]], stats: dict[str, int]
) -> None:
    table = mention_table(posts)
    scores = sorted(p["score"] for p in posts)
    print(f"posts={len(posts)} news={len(news)} authors={stats['authors']}")
    print(
        f"bot_posts={stats['bot_posts']} spam_campaign={stats['spam_campaign_posts']} "
        f"prolific_owala={stats['prolific_owala_posts']} generic={stats['generic_posts']} "
        f"empty_entities={sum(1 for p in posts if not p['entities'])}"
    )
    print(f"score median={scores[len(scores) // 2]} max={scores[-1]}")
    print(
        f"near_duplicates (non-campaign, 3-shingle jaccard>=0.8)={stats['near_dupes']}/{stats['dedupe_considered']} "
        f"({stats['near_dupes'] / stats['dedupe_considered']:.2%})"
    )
    print(f"{'entity':<20}{'base/day':>10}{'recent/day':>12}{'news':>6}")
    news_counts = Counter(n["query"] for n in news)
    for name, (b, r) in table.items():
        print(f"{name:<20}{b:>10.1f}{r:>12.1f}{news_counts[name]:>6}")


# --------------------------------------------------------------------------------------
def write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--scale",
        type=float,
        default=DEFAULT_SCALE,
        help="multiplier on every entity's Reddit rate (1.0 = the literal per-entity rates in the spec)",
    )
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    args = parser.parse_args()

    rng = random.Random(SEED)
    args.out.mkdir(parents=True, exist_ok=True)

    posts, stats = generate_posts(rng, args.scale)
    pageviews = generate_pageviews(rng)
    news = generate_news(rng)
    stats["near_dupes"], stats["dedupe_considered"] = near_duplicate_rate(posts)

    write_jsonl(args.out / "reddit_posts.jsonl", posts)
    (args.out / "pageviews.json").write_text(json.dumps(pageviews, indent=1), encoding="utf-8")
    write_jsonl(args.out / "news_items.jsonl", news)
    write_readme(args.out / "README.md", posts, news, stats, args.scale)

    print_stats(posts, news, stats)
    for name in ("reddit_posts.jsonl", "pageviews.json", "news_items.jsonl", "README.md"):
        print(f"{name}: {(args.out / name).stat().st_size:,} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
