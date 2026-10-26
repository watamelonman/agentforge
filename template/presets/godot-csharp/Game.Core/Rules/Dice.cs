namespace Game.Core.Rules;

using System;

/// <summary>
/// Deterministic dice roller. Rules code never uses an unseeded RNG, so every battle can be
/// replayed exactly from its seed in headless tests. Uses a built-in SplitMix64 generator
/// instead of <see cref="Random"/>, whose sequence is not guaranteed across .NET versions.
/// Sample code: replace with your project's own RNG if the spec names one.
/// </summary>
public sealed class Dice
{
    private ulong _state;

    /// <summary>Creates a roller whose sequence is fully determined by <paramref name="seed"/>.</summary>
    public Dice(int seed) => _state = unchecked((ulong)seed);

    /// <summary>Rolls <paramref name="count"/> dice with <paramref name="sides"/> faces; returns the total.</summary>
    /// <exception cref="ArgumentOutOfRangeException">count or sides is not positive.</exception>
    public int Roll(int count, int sides)
    {
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(count);
        ArgumentOutOfRangeException.ThrowIfNegativeOrZero(sides);
        int total = 0;
        for (int i = 0; i < count; i++)
        {
            total += (int)(NextUInt64() % (ulong)sides) + 1;
        }

        return total;
    }

    /// <summary>Advances the SplitMix64 state and returns the next 64-bit value.</summary>
    private ulong NextUInt64()
    {
        unchecked
        {
            ulong z = _state += 0x9E3779B97F4A7C15UL;
            z = (z ^ (z >> 30)) * 0xBF58476D1CE4E5B9UL;
            z = (z ^ (z >> 27)) * 0x94D049BB133111EBUL;
            return z ^ (z >> 31);
        }
    }
}
