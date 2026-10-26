## Deterministic dice roller for simulation code.
##
## Sim code must never call randf()/randi(): results must be reproducible from a seed so
## battles can be replayed headless in tests. See docs/ENGINE.md "Determinism".
class_name Dice
extends RefCounted

var _rng: RandomNumberGenerator = RandomNumberGenerator.new()


## Creates a roller whose sequence is fully determined by [param seed_value].
func _init(seed_value: int) -> void:
	_rng.seed = seed_value


## Rolls [param count] dice with [param sides] faces and returns the total.
## Fails loudly on invalid input instead of returning 0 silently.
func roll(count: int, sides: int) -> int:
	assert(count > 0 and sides > 0, "Dice.roll: count and sides must be positive")
	var total: int = 0
	for _i: int in count:
		total += _rng.randi_range(1, sides)
	return total
