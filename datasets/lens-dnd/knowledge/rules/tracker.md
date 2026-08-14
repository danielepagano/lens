USING A D&D INITIATIVE TRACKER

A `tracker.*` object in your context means the player is tracking this fight inside Lens: initiative order, HP, conditions, expended resources. `tracker._template` is how a tracker gets built; this is how to read one while you play.

IT IS THE CANONICAL STATE

Treat the tracker as true. It outranks your memory of earlier beats and it outranks anything you would otherwise have tried to hold in your head.

You CANNOT update it. Do not narrate changes to it, do not tell the player to tick a box, and do not restate what it already shows. Reporting HP totals back to a player who is looking at them is noise.

READING YOUR CUE

The player will hand you the fight with something like "we're at initiative 18". From the tracker you can see:

- which entries between there and the next PC entry are yours to run,
- what each of them is — the entry links its `stat.*`, `npc.*`, or `pc.*` object,
- their current condition: HP remaining, conditions noted, whether the Reaction is spent, which limited abilities are used up.

Declare the actions of every actor you control from that point down to the next initiative the player owns, then stop. Do not run past a PC's turn.

WHAT IT CHANGES ABOUT YOUR NARRATION

- A creature shown at or below half its maximum HP is Bloodied. Narrate it, and let it change behaviour.
- A creature whose Reaction is already spent cannot make an Opportunity Attack this round. Do not threaten one.
- A limited ability shown as used is gone. Pick something else.
- Conditions listed on an entry are live constraints on what that creature can attempt this turn.

If the tracker and the prose disagree, the tracker is right and the prose was stale — continue from the tracker without arguing about it.
