<!-- run 1, before Gateway restart -->

# IBKR capability measurement - raw responses

- Run at: 2026-08-19T07:11:47.680608+00:00
- Account: DUQ200898
- clientId: 99 (read-only connection)

| call | outcome | count |
|---|---|---|
| `IB.managedAccounts()` | **data** | 1 |
| `IB.fills()` | **empty** | 0 |
| `IB.reqExecutions()` | **empty** | 0 |
| `IB.openTrades()` | **empty** | 0 |
| `IB.reqAllOpenOrders()` | **empty** | 0 |
| `IB.positions()` | **empty** | 0 |
| `announcements - no IB equivalent exists` | **absent** | - |

permIds observed: none

## Raw responses

### `IB.managedAccounts()` - data

Is this the PAPER session? Paper accounts are prefixed DU.

```
['DUQ200898']
```

### `IB.fills()` - empty

recent_fills: what does this session's fill history look like? Documented as 'all fills from this session', so it CANNOT see a fill that happened while the app was down - the case absorb_broker_fills exists for.

```
[]
```

### `IB.reqExecutions()` - empty

recent_fills: how far back do executions actually go? This is the retention measurement - IB.fills() cannot answer it.

```
[]
```

### `IB.openTrades()` - empty

resting_stops / resting_stop_orders: is a stop VISIBLE to the API? If a simulated stop is invisible here, protection verification silently stops working - the app's strongest safety claim.

```
[]
```

### `IB.reqAllOpenOrders()` - empty

resting_stops: does the all-orders call agree with openTrades()? A disagreement is itself the finding.

```
[]
```

### `IB.positions()` - empty

Context for the stop question: what does the account hold?

```
[]
```

### `announcements - no IB equivalent exists` - absent

announcements: is there any structured corporate-action feed? M39's ex-date gate is the piece observed working in production.

```
No structured corporate-action feed. Measured against ib_async 2.1.0: reqFundamentalData returns XML report documents and reqHistoricalNews returns unstructured headline text. Neither is an announcements feed in the shape M39's detector consumes, so this is a decision to record (Task 5), not code to write.
```
