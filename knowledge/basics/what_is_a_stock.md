---
id: what-is-a-stock
title: "What is a stock: shares, ownership, and why prices move"
source: "SEC investor.gov, Stocks (Introduction to Investing); OCC, Characteristics and Risks of Standardized Options, chapter X"
url: https://www.investor.gov/introduction-investing/investing-basics/investment-products/stocks
kind: basics
level: beginner
as_of: 2026-11-04
---

# What is a stock: shares, ownership, and why prices move

A **stock** is a security that represents ownership in a company. Ownership is divided into **shares**, and each share is one equal slice of the whole. A company with 1 billion shares outstanding that you hold 100 shares of belongs to you to the extent of 100 divided by 1 billion, or one ten-millionth. That slice carries two things: a claim on the company's profits after everyone else is paid, and, for common stock, a vote on matters such as electing the board of directors.

## What a shareholder actually owns

A shareholder does not own the company's buildings or bank accounts directly; the corporation owns those. The shareholder owns a **residual claim**: whatever is left after employees, suppliers, lenders and the tax authorities are paid. Profits can be returned to shareholders as **dividends** (cash payments per share) or by **buybacks** (the company purchases its own shares, so each remaining share is a larger slice), or kept inside the business to grow it. Common stock is the last claim in line if a company fails, which is the main reason it is riskier than a bond from the same company and also the reason it has historically earned more over long periods.

## Why prices move

A share's price is simply the last price at which a buyer and a seller agreed to trade on an exchange. It moves because expectations change. News about earnings, a new product, interest rates, a lawsuit or the wider economy changes what investors believe the company's future profits are worth today. Prices also move for reasons that have nothing to do with the company, such as a large fund selling to meet withdrawals. Over a single day the movement is mostly noise; over years it tends to track the growth or decline of the business itself. No model, including anything in this app, can tell in advance which direction a price goes next.

## Owning 100 shares versus being obliged to buy 100 shares

This distinction matters for anyone reading a cash-secured put screen. Suppose a stock trades at $52 and an investor buys 100 shares for $5,200. The investor owns the shares today, receives any dividends, and gains or loses one dollar for every one dollar move in the price.

Now suppose instead the investor sells one put with a $50 strike expiring in 40 days and collects a $1.20 premium, or $120 per contract. The investor owns nothing yet. What they hold is an **obligation**: if the put holder exercises, the writer is obliged to buy 100 shares at $50, for $5,000, regardless of where the stock trades at that moment. The OCC disclosure document describes this plainly: a put writer bears the risk of a decline in the stock all the way to zero. In exchange, the writer keeps the $120 whatever happens. If the stock stays above $50, the obligation expires and no shares change hands; if it falls to $40, the writer pays $5,000 for shares worth $4,000, offset only by the $120. Shareholders receive dividends and can vote; a put writer receives neither until assignment turns the obligation into shares.

## What can go wrong

Share prices can fall to zero if a company fails, and no amount of past dividend history prevents that. A single stock can also drop 20% or more in one day on earnings news. Beginners sometimes read "ownership" as "safety"; it is not. Owning shares concentrates an investor's result on one company's fortunes, and an obligation to buy shares through a short put carries the same downside from the strike price onward.

## Where this shows up in OptionsScout

The app's whole premise rests on this distinction. The Quality Screen tab filters the curated "good-to-own" universe through a deterministic quality gate (price at or above $20, average volume at or above 1 million shares, 30-day realised volatility at or below 35%, and more) so that every short put the Candidates tab lists is on a company the user would accept owning if the obligation becomes shares. The Portfolio & Risk tab then treats each CSP as if the shares might be bought, reporting the **realistic loss** as the loss if the stock drops 30% at expiry, not the premium at risk.

## Sources

- SEC investor.gov, *Stocks*: https://www.investor.gov/introduction-investing/investing-basics/investment-products/stocks
- SEC investor.gov, *Introduction to Investing*: https://www.investor.gov/introduction-investing
- OCC, *Characteristics and Risks of Standardized Options*, chapter X (risks of option writers): https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
