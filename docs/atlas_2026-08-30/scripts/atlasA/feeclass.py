"""Map Polymarket category tags (archive `category`, `category_refined`) + slug to fee-schedule classes."""
import re
CLASSES=['crypto_updown','crypto_other','sports','esports_tennis','finance','finance_macro','politics_us','geopolitics_world','culture','tech_science','weather','meta_other']
_EXACT={
 # crypto short-horizon price markets (Jan-2026 rollout)
 'Up or Down':'crypto_updown','5M':'crypto_updown','15M':'crypto_updown','1H':'crypto_updown','4H':'crypto_updown','Crypto Prices':'crypto_updown',
 'Weekly':'crypto_updown','Monthly':'crypto_updown','Hit Price':'crypto_updown','Recurring':'crypto_updown','Hide From New':'crypto_updown','Today':'crypto_updown','Daily':'crypto_updown',
 # other crypto
 'Crypto':'crypto_other','Bitcoin':'crypto_other','Ethereum':'crypto_other','Solana':'crypto_other','XRP':'crypto_other','Ripple':'crypto_other','Monad':'crypto_other','MicroStrategy':'crypto_other',
 'Stablecoins':'crypto_other','Token':'crypto_other','Airdrops':'crypto_other','ATH':'crypto_other','FDV':'crypto_other','Satoshi':'crypto_other','MegaETH':'crypto_other','hyperliquid':'crypto_other','Lighter':'crypto_other','Public Sales':'crypto_other','Metadao':'crypto_other','Zama':'crypto_other','Makina':'crypto_other','Multi Strikes':'crypto_other','Neg Risk':'crypto_other',
 # sports
 'Sports':'sports','Basketball':'sports','Soccer':'sports','NBA':'sports','NFL':'sports','NCAA':'sports','NCAA Basketball':'sports','NCAA Football':'sports','MLB':'sports','MLB Playoffs':'sports','NHL':'sports','Premier League':'sports','EPL':'sports','MLS':'sports','Boxing':'sports','UFC':'sports','Formula 1':'sports','F1 Singapore Grand Prix':'sports','Grand Prix':'sports','bundesliga':'sports','Bundesliga 2':'sports','La Liga':'sports','La Liga 2':'sports','Ligue 1':'sports','Cricket':'sports','International Cricket':'sports','Hockey':'sports','football':'sports','baseball':'sports','Champions League':'sports','Super Bowl':'sports','Olympics':'sports','2026 Winter Games':'sports','Medal Count':'sports','Darts':'sports','Chess':'sports','Concacaf Nations League':'sports','UEF Qualifiers':'sports','Afcon':'sports','Africa Cup of Nations':'sports','CFB':'sports','CFB Playoffs':'sports','NFL Playoffs':'sports','World Series':'sports','EFL Championship':'sports','Australian A-League':'sports','2026 NBA Playoffs':'sports','Big Game':'sports','LMB':'sports','Golf':'sports','Rugby':'sports','Serie A':'sports','Cycling':'sports','Racing':'sports',
 # esports / tennis
 'Esports':'esports_tennis','Tennis':'esports_tennis','league of legends':'esports_tennis','LoL Worlds 2025':'esports_tennis','counter strike 2':'esports_tennis','counter-strike':'esports_tennis','Dota 2':'esports_tennis','Valorant':'esports_tennis','Wimbledon':'esports_tennis','video games':'esports_tennis','Games':'esports_tennis',
 # finance (stocks, indices, commodities, corporate)
 'Finance':'finance','SPX':'finance','NYMEX Crude Oil Futures':'finance','COMEX Gold Futures':'finance','Gold':'finance','Commodities':'finance','Equities':'finance','Earnings':'finance','Stocks':'finance','NVDA':'finance','AMZN':'finance','NFLX':'finance','TSLA':'finance','AAPL':'finance','GOOGL':'finance','MSFT':'finance','PLTR':'finance','Meta':'finance','Apple':'finance','netflix':'finance','google':'finance','Tesla':'finance','Big Tech':'finance','IPO':'finance','IPOs':'finance','Oil':'finance','Indicies':'finance','DJI':'finance','NDX':'finance','RUT':'finance','NIK':'finance','S&P':'finance','Pre-Market':'finance','Derivatives':'finance','Continental Futures':'finance','Business':'finance','App Store':'finance','OPEN':'finance','HGV':'finance','Parlays':'finance','Mexico':'finance','Canada':'finance','France':'finance',
 # macro / policy rates (schedule status ambiguous)
 'Fed Rates':'finance_macro','Fed':'finance_macro','Jerome Powell':'finance_macro','Economy':'finance_macro','Economic Policy':'finance_macro','Inflation':'finance_macro','CPI':'finance_macro','unemployment':'finance_macro','Macro Indicators':'finance_macro','Macro':'finance_macro','Global Rates':'finance_macro','Trade War':'finance_macro','Tariffs':'finance_macro','Gov Shutdown':'finance_macro','shutdown':'finance_macro',
 # US politics
 'Politics':'politics_us','Trump':'politics_us','Elections':'politics_us','Congress':'politics_us','President':'politics_us','U.S. Politics':'politics_us','primary elections':'politics_us','Midterms':'politics_us','Senate':'politics_us','NJ Governor':'politics_us','NYC Mayor':'politics_us','nyc':'politics_us','New York City':'politics_us','Mamdani':'politics_us','Sliwa':'politics_us','Courts':'politics_us','DHS':'politics_us','SOTU':'politics_us','Trump Cabinet':'politics_us','Trump Presidency':'politics_us','California Midterm':'politics_us','Alaska Midterm':'politics_us','Minnesota':'politics_us','Main Election':'politics_us','Epstein':'politics_us','US Election':'politics_us','United States':'politics_us','2025 Predictions':'politics_us','Featured':'politics_us','Enrich':'politics_us','Extend':'politics_us','skr':'politics_us','election':'politics_us','strike':'politics_us','Military':'politics_us','Pandemics':'politics_us','Global Elections':'politics_us','World Elections':'politics_us',
 # geopolitics / world (fee-exempt per schedule)
 'Geopolitics':'geopolitics_world','World':'geopolitics_world','Iran':'geopolitics_world','Israel':'geopolitics_world','Middle East':'geopolitics_world','Ukraine':'geopolitics_world','Gaza':'geopolitics_world','Foreign Policy':'geopolitics_world','Venezuela':'geopolitics_world','Khamenei':'geopolitics_world','Reza Pahlavi':'geopolitics_world','Mojtaba':'geopolitics_world','Trump-Zelenskyy':'geopolitics_world','Trump-Putin':'geopolitics_world','putin':'geopolitics_world','Russia':'geopolitics_world','China':'geopolitics_world','Denmark':'geopolitics_world','Peru':'geopolitics_world','Romania':'geopolitics_world','Hungary':'geopolitics_world','Hungary Election':'geopolitics_world','French Election':'geopolitics_world','Poland':'geopolitics_world','Brazil':'geopolitics_world','Japan':'geopolitics_world','Bolivia':'geopolitics_world','Bolivia Elections':'geopolitics_world','Vietnam':'geopolitics_world','Thailand-Cambodia':'geopolitics_world','Strait':'geopolitics_world','houthi':'geopolitics_world','Hezbollah':'geopolitics_world','Iran Ceasefire':'geopolitics_world','U.S. x Iran':'geopolitics_world','Davos':'geopolitics_world','Starmer':'geopolitics_world','Orban':'geopolitics_world','Fidesz':'geopolitics_world','Trump-Machado':'geopolitics_world','maduro':'geopolitics_world','sea':'geopolitics_world','hack':'geopolitics_world','zelensky':'geopolitics_world','Allah':'geopolitics_world','London':'geopolitics_world','LA':'geopolitics_world','UK':'geopolitics_world','South':'geopolitics_world','referendum':'geopolitics_world','Trump x Saudi':'geopolitics_world','Africa':'geopolitics_world','Bolivia':'geopolitics_world',
 # culture
 'Culture':'culture','Movies':'culture','box office':'culture','Music':'culture','Awards':'culture','Grammys':'culture','Oscars':'culture','MrBeast':'culture','YouTube':'culture','TikTok':'culture','Celebrities':'culture','Reality TV':'culture','Reality':'culture','Eurovision':'culture','Mentions':'culture','Tweet Markets':'culture','Elon Musk':'culture','Pokemon':'culture','Top Netflix':'culture','spotify':'culture','magazine':'culture','The Odyssey':'culture','badbunny':'culture','andrew tate':'culture','Christmas':'culture','Game Specials':'culture','James':'culture','internet':'culture','Clavicular':'culture','opinion':'culture','prize':'culture','list':'culture','Aliens':'culture',
 # tech / science
 'Tech':'tech_science','AI':'tech_science','OpenAI':'tech_science','Gemini 3':'tech_science','Claude 5':'tech_science','Claude':'tech_science','DeepSeek':'tech_science','SpaceX':'tech_science','Space':'tech_science','Science':'tech_science','Climate & Science':'tech_science','Climate':'tech_science','climate':'tech_science','ai':'tech_science','lol':'tech_science','transit':'tech_science','free solo':'tech_science','Sci-Tech':'tech_science',
 # weather
 'Weather':'weather','Daily Temperature':'weather','Weather & Science':'weather',
}
_META=re.compile(r'^(Rewards|Depreciated|Deprec|Parent For Derivative|All|us|exchange|Neg Risk)', re.I)
_UPDOWN=re.compile(r'(updown|up-or-down|-above-|-below-|-dip-to-|-reach-|hit-\$|price-on|-ath-)', re.I)
_SPORT_SLUG=re.compile(r'-vs-|-win-the-|-spread-|-moneyline|-o-u-|-total-|-points|-touchdown', re.I)
_TENNIS=re.compile(r'(atp|wta|tennis|open-|wimbledon|roland)', re.I)
_ESPORT=re.compile(r'(lol-|cs2|csgo|dota|valorant|esports|league-of-legends|counter-strike)', re.I)
_COIN=re.compile(r'(bitcoin|btc|ethereum|-eth-|^eth-|solana|-sol-|^sol-|xrp|doge|bnb|hype-|crypto)', re.I)
def map_market(category, category_refined, slug):
    cat=category or ''; ref=category_refined or ''; s=slug or ''
    # slug overrides for structural market types
    if _UPDOWN.search(s) and (_COIN.search(s) or cat in ('Up or Down','Crypto Prices','5M','15M','1H','4H','Recurring','Hide From New','Weekly','Monthly','Hit Price','Neg Risk') or 'Rewards' in cat):
        return 'crypto_updown'
    if cat in _EXACT: return _EXACT[cat]
    if _META.search(cat):
        # meta tags: fall back to refined category / slug
        if ref in _EXACT: return _EXACT[ref]
        if ref=='Price Action' or ref=='Crypto': return 'crypto_other'
        if ref=='Sports': return 'sports'
        if ref=='Politics': return 'politics_us'
        if ref=='Finance': return 'finance'
        if ref=='Culture': return 'culture'
        if _SPORT_SLUG.search(s): return 'sports'
        if _COIN.search(s): return 'crypto_other'
        return 'meta_other'
    if ref in _EXACT: return _EXACT[ref]
    if ref=='Price Action': return 'crypto_updown'
    if ref=='Sports':
        return 'esports_tennis' if (_TENNIS.search(s) or _ESPORT.search(s)) else 'sports'
    if ref=='Politics': return 'politics_us'
    if ref=='Finance': return 'finance'
    if ref=='Culture': return 'culture'
    if ref=='Crypto': return 'crypto_other'
    if ref=='Sci-Tech': return 'tech_science'
    if _SPORT_SLUG.search(s): return 'sports'
    if _COIN.search(s): return 'crypto_other'
    return 'meta_other'
