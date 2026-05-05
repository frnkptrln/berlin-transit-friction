# Friction Model

A **friction event** is a public signal that the transport system deviates from expected, legible, or comfortable operation.

## Categories
- delay
- cancellation
- disruption
- construction
- replacement_service
- skipped_stop
- platform_change
- elevator_or_accessibility_issue
- information_gap
- crowding_signal
- unknown

## Severity
- 0 = informational
- 1 = minor
- 2 = moderate
- 3 = severe
- 4 = network-critical

## Notes
- Crowding is hard to infer from public operational data.
- This project does **not** pretend to measure crowding unless a concrete source exists.
- In the MVP, crowding is treated as future/manual signal category.
