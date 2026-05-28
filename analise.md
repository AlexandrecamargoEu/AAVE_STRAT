[27/05/2026 17:57] Paul: from the snapshot claude isn't finding anything either
[27/05/2026 17:57] Paul: i'm gonna have to find live examples to then see if the snapshots are lining up properly
[27/05/2026 18:07] Paul: on BSC chain there seems to be a profitable route
[27/05/2026 18:09] Paul: deposit USDT on Venus (+5%, some in shitcoin) -> borrow USDC (-2.45%) -> deposit USDC on Kinza.finance (7%, some in shitcoin) -> borrow  btcb (-0.5%) -> deposit the btcb on Venus again to borrow usdc -> deposit usdc on kinza.finance again
[27/05/2026 18:09] Paul: this considers shitcoins which you may not have been considering (I don't remember atm)
[27/05/2026 18:10] Paul: ill try to find an example that doesn't include shitcoins

![alt text](image.png)

[27/05/2026 18:23] Paul: there is definitely opportunity when we look cross-chain. Here we can deposit USDC on sonic for 15% and borrow this for 3-4% in another cheap chain :

---

[reply]

yeah you're right, I dug into it and found exactly what's going on.

DefiLlama just isn't counting the reward APY. for Venus, the data literally has the XVS token address sitting right there in the payload but reports the reward as 0%. so our snapshot only saw Venus's ~2% base and completely missed the ~3% in XVS you see on the actual UI. same with Kinza — rewards show up as null and it only sees like 200k TVL there. and Sonic Market, that 18M protocol in your screenshot? not even indexed by DefiLlama, it only has some tiny pools on the Sonic chain, not the real one.

so "no positive loops" was half the market actually drying up and half us being blind to the reward data. good catch, this changes how we build it.

couple flags on those routes before we get excited though:

that Sonic USDC at 15% isn't rewards, it's because the pool is at ~99.7% utilization. there's only like 10k left to withdraw out of 3.5M. so you'd earn the 15% but you could be stuck not being able to pull your money until people repay. the high APY is basically the pool paying you to be trapped. gotta check exit liquidity before putting size in.

and that BSC route uses BTCB in the middle, so that's bitcoin price exposure, the stuff we said we'd avoid. not saying don't, just that it's a different risk than pure stables.

the fix: we stop trusting DefiLlama for reward numbers. use it just to find what pools exist, then pull the real reward APY ourselves on-chain (read Venus's emission rate × XVS price ÷ TVL). I'll get you accurate numbers once that's hooked up.
