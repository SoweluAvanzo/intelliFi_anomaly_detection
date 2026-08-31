
Polymarket is a decentralized prediction market where the
price of a share behaves like a crowd-sourced probability. Because the markets
are public and run on a blockchain, every trade and every wallet's positions are visible —
but that same openness makes them a target for abuse: a few large traders can
push prices around, traders can wash-trade to fake volume, well-connected accounts can
trade on private information, and clusters of accounts can coordinate or copy each other.

The academic literature on these markets describes manipulation taxonomies but offers
almost no working tools to actually detect such behaviour from the data Polymarket exposes.
I address three concrete gaps, phrased as research questions:

- **RQ1 — Measuring manipulation-consistent signals.** Can signals consistent with
  manipulation — the concentration of a market's flow in a few whales, wash-trading
  round-trips, and markets that remain mispriced until close — be quantified directly from
  public market, trade, and on-chain data?
- **RQ2 — Coordination and copy-trading.** Can coordinated groups of accounts and
  copy-trading/herding behaviour be identified and measured from the combination of
  on-chain transfers and the timing of their trades?
- **RQ3 — Skill versus information.** Can accounts that consistently win more than the
  prices they paid imply be distinguished as a signal of insider-consistent trading?

I collect the raw material from Polymarket's free public endpoints (market metadata,
executed trades, holder snapshots, price histories) and from the Polygon blockchain
(transfers of stablecoins and outcome tokens between wallets). The loaders save every raw
response before processing, skip data already fetched, and put all timestamps on one common
UTC clock, so the dataset is reproducible and can be re-run safely. The corpus analysed
here is 100 of the highest-volume resolved markets and 382,554 trades.

On this data I apply four methods. Concentration analysis (Gini, Herfindahl index,
Lorenz curves) measures how much of a market's activity is controlled by a handful of
wallets. Bayesian skill calibration estimates each wallet's true win rate and compares
it to the probability it paid at entry; the gap between the two is how I measure the edge of a wallet.
Entity resolution and coordination analysis builds two networks — who sends money to
whom on-chain, and who trades the same markets at the same moments — merges them, and uses
community detection algorithms to find clusters, then extracts copy-trading leader–follower pairs and
wash-trading patterns. Finally, a mirror-strategy backtest asks whether blindly
copying a suspicious group of wallets would have been profitable based on realistic fees and
delays, which tests whether the detected patterns reflect real, exploitable advantage.

# Limitations and proposal for future work and research collaboration

 In this work we only focus on Polymarket. My suggestion is that we apply the methodologies mentioned above on alternative prediction markets. It would make sense to expand the work to include multiple markets. Some examples could include: Augur, Omen, Zeitgeist. This could allow us to: identify similarities and differences in pricing of probabilities of same/similar events between different prediction market platforms and compare the trading patterns among these platforms. This would allow us to identify trading networks that span across and adopt multiple platforms.