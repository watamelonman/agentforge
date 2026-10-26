# GdUnit4 suite for Dice. Tests run headless via tools/godot_check.sh test.
extends GdUnitTestSuite


func test_same_seed_same_sequence() -> void:
	var a: Dice = Dice.new(42)
	var b: Dice = Dice.new(42)
	for _i: int in 20:
		assert_int(a.roll(2, 6)).is_equal(b.roll(2, 6))


func test_roll_within_bounds() -> void:
	var d: Dice = Dice.new(7)
	for _i: int in 200:
		assert_int(d.roll(3, 6)).is_between(3, 18)
