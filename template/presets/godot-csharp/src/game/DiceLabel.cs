namespace Game;

using Game.Core.Rules;
using Godot;

/// <summary>Example thin presentation node: shows a roll from the pure-C# rules library.</summary>
public partial class DiceLabel : Label
{
    /// <summary>Seed exposed to the editor so designers can tweak it in the inspector.</summary>
    [Export] public int Seed { get; set; } = 1;

    /// <inheritdoc/>
    public override void _Ready() => Text = new Dice(Seed).Roll(2, 6).ToString(System.Globalization.CultureInfo.InvariantCulture);
}
