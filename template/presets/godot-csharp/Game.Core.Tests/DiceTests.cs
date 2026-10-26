namespace Game.Core.Tests;

using System;
using Game.Core.Rules;
using Xunit;

public sealed class DiceTests
{
    [Fact]
    public void Same_seed_gives_same_sequence()
    {
        var a = new Dice(42);
        var b = new Dice(42);
        for (int i = 0; i < 20; i++)
        {
            Assert.Equal(a.Roll(2, 6), b.Roll(2, 6));
        }
    }

    [Fact]
    public void Rolls_stay_within_bounds()
    {
        var d = new Dice(7);
        for (int i = 0; i < 200; i++)
        {
            Assert.InRange(d.Roll(3, 6), 3, 18);
        }
    }

    [Fact]
    public void Invalid_input_throws() =>
        Assert.Throws<ArgumentOutOfRangeException>(() => new Dice(1).Roll(0, 6));
}
