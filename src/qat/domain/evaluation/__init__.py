"""Evaluation (M51): not whether the system recorded something, but whether
what it recorded is used, and whether that use adds value.

Everything else in this application answers "is the information being
captured". This package asks the next question, and it is a harder one: a field
faithfully recorded, correctly displayed and never acted on is pure cost, and a
signal acted on that degrades outcomes is worse than cost. Neither shows up as a
failed test or a red line in a log.

Read-only by construction. Nothing here places, sizes, refuses or approves
anything - it reads records the application has already written. That is what
lets it be built during the validation freeze.
"""
