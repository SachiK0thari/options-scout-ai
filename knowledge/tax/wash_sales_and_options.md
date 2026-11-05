---
id: wash-sales-and-options
title: "Wash sales and options: how the 61-day window reaches a short put"
source: "26 U.S.C. §1091 (loss from wash sales of stock or securities); IRS Publication 550, chapter 4, Wash Sales"
url: https://www.law.cornell.edu/uscode/text/26/1091
kind: tax
level: advanced
as_of: 2026-11-04
---

# Wash sales and options: how the 61-day window reaches a short put

A **wash sale** is a sale of stock or securities at a loss where, within a window around the sale, the seller acquires substantially identical stock or securities, or a contract or option to acquire them. Section 1091 of the Internal Revenue Code disallows the loss for the year of sale. A short put can end in stock, which is how the rule reaches a put writer. This is education, not tax advice; rules change and individual situations differ, so confirm with a tax professional or the IRS publication cited.

## The 61-day window

The window runs from 30 days before the loss sale to 30 days after it, which with the sale day itself is 61 calendar days. Any acquisition of substantially identical stock inside that span, in any account the taxpayer controls, is a replacement purchase. IRS Publication 550, in the "Wash Sales" section, lists the ways an acquisition can occur: buying the stock, acquiring it in a fully taxable trade, acquiring a contract or option to acquire it, or acquiring it in an IRA or Roth IRA. The rule applies to losses on options as well as on stock: Publication 550 says losses from the sale, exchange, or termination of an option to acquire or sell stock are subject to the wash sale rules.

## How a cash-secured put can trigger it

Consider an investor who sells 100 shares of a stock at a loss and, within 30 days, is assigned on a put written on that same stock. The assignment is an acquisition of substantially identical stock inside the window, so the earlier loss is disallowed. Publication 550 and the Internal Revenue Service's published rulings also treat writing a put as acquiring a contract to acquire the stock when, at the time it is written, the put is so far in the money that exercise is close to certain. A 0.15-0.30 delta put of the kind this app screens is out of the money when written, so the mere writing of it is usually not the trigger; the assignment is. The precise test is in Publication 550 under "Wash Sales", which should be read for edge cases rather than relying on a delta rule of thumb.

## What happens to the disallowed loss

The loss is not gone. Section 1091(d) adds the disallowed amount to the basis of the replacement shares, and the holding period of the old shares is tacked on to the new ones. Suppose the investor sold 100 shares at a $300 loss and, 10 days later, was assigned on a $50 put written for a $1.20 premium. The new shares have a basis of $48.80 per share from the assignment, plus $3.00 per share of disallowed loss, giving $51.80. When those shares are finally sold outside a new window, the deferred loss is realised through the higher basis. The rule changes timing, not the total, as long as the replacement shares stay in a taxable account.

## The IRA exception to that comfort

If the replacement shares are acquired inside an IRA or Roth IRA, Publication 550 says the loss is disallowed and the basis of the IRA shares is not increased, so the loss is lost permanently rather than deferred.

## What can go wrong

Brokers are required to report wash sales on Form 1099-B only for identical securities within the same account, so a loss in one account and an assignment in another will not be flagged for the taxpayer. Monthly puts on one stock mixed with occasional share sales produce overlapping windows that are tedious to untangle. A disallowed loss near year-end moves a deduction into the following year.

## Where this shows up in OptionsScout

The Portfolio & Risk tab's planned holdings section will record acquisition dates for assigned shares, and the Tax & Accounts page in Learn links to this document when a user asks the Scout chat about selling a stock they also write puts on. The app does not compute wash sale adjustments; it points to the broker's 1099-B and this rule.

## Sources

- 26 U.S.C. Section 1091, loss from wash sales of stock or securities: https://www.law.cornell.edu/uscode/text/26/1091
- IRS Publication 550, *Investment Income and Expenses*, chapter 4, "Wash Sales": https://www.irs.gov/publications/p550
- IRS Form 1099-B, Proceeds From Broker and Barter Exchange Transactions: https://www.irs.gov/forms-pubs/about-form-1099-b
