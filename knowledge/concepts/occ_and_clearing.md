---
id: occ-and-clearing
title: "The OCC and clearing: who stands behind every listed option and how assignment is allocated"
source: "OCC, Characteristics and Risks of Standardized Options, chapter I (Introduction) and chapter VIII (Exercise and Settlement); FINRA Rule 2360"
url: https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
kind: concepts
level: beginner
as_of: 2026-11-13
---

# The OCC and clearing

The **Options Clearing Corporation** (OCC) is the clearinghouse for every listed option traded on a U.S. exchange. When a buyer and a seller agree on a trade, the exchange reports it to the OCC, which then steps between them: the OCC becomes the seller to every buyer and the buyer to every seller. This substitution is called **novation**, and it is why a retail option writer never needs to know who bought the contract.

## What the OCC does

The OCC is a clearing agency registered with the Securities and Exchange Commission and designated a systemically important financial market utility. Its members are **clearing members**, large broker-dealers and banks. Every day the OCC:

- records every opening and closing trade and computes open interest for each series;
- collects margin, in cash and securities, from clearing members with short positions, sized to cover what those positions could lose;
- maintains a clearing fund contributed by all members as a second layer of protection;
- processes exercises submitted by holders and assigns the matching obligations to writers.

Because of this structure, the contract a put writer sells is a contract with the OCC. If the original buyer's broker fails, the OCC's obligations to the writer are unchanged.

## The options disclosure document

The booklet *Characteristics and Risks of Standardized Options*, usually called the **ODD** or the options disclosure document, is published by the OCC and is the official description of how listed options work and what can go wrong with them. FINRA Rule 2360 requires a broker to deliver it to a customer at or before the time the account is approved for options trading. It is the primary source cited throughout this app's knowledge base.

## How assignment is allocated

When a holder exercises, their broker submits the exercise to the OCC through its clearing member. The OCC then **assigns** the exercise to a clearing member with a short position in that series, chosen by a random process. The clearing member in turn allocates the assignment to one of its own customers who is short the series, using a method it must disclose to customers under FINRA Rule 2360: random selection or first-in, first-out are the usual choices. Suppose 5,000 contracts of a $50 put are open and 300 are exercised on a given night. Three hundred writers learn the next morning that they have bought 100 shares each at $50; the other 4,700 contracts are untouched. A writer with ten contracts open may be assigned on three of them, and cannot influence which.

## Why counterparty risk is not the retail writer's problem

In an over-the-counter contract, each party bears the risk that the other fails to perform. In a listed option, the OCC's novation, member margin and clearing fund put that risk on the clearinghouse and its members instead. The retail writer's exposure is therefore to the market, through the terms of the contract, and to their own broker as custodian of their cash and shares. The second of these is covered by SIPC up to its limits for custody failures, though never for market losses.

## What can go wrong

The protection is against a counterparty's default, not against the position. A put writer still owns the shares at the strike after assignment, however far the stock has fallen. Partial assignment of a multi-contract position is normal. And the broker, not the OCC, is the writer's point of contact: the exercise cut-off time, the allocation method and the margin call that may follow are all broker rules.

## Where this shows up in OptionsScout

Every Sources section in the Learn tab that cites the OCC is citing the ODD described above, and the Compliance agent requires that each explanation carry such a citation. The *Assignment* document in Learn describes the mechanics of being assigned on a cash-secured put; this one explains who does the assigning.

## Sources

- OCC, *Characteristics and Risks of Standardized Options*, chapter I (Introduction) and chapter VIII (Exercise and Settlement): https://www.theocc.com/company-information/documents-and-archives/options-disclosure-document
- FINRA Rule 2360, Options (delivery of the disclosure document): https://www.finra.org/rules-guidance/rulebook/finra-rules/2360
- SIPC, what SIPC protects: https://www.sipc.org/for-investors/what-sipc-protects
