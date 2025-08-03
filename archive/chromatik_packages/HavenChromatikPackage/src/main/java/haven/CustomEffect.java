package heronarts.lx.example;

import heronarts.lx.LX;
import heronarts.lx.LXCategory;
import heronarts.lx.LXComponentName;
import heronarts.lx.color.LXColor;
import heronarts.lx.effect.LXEffect;
import heronarts.lx.parameter.CompoundParameter;

@LXCategory("Custom")
@LXComponentName("Custom")
public class CustomEffect extends LXEffect {

  public final CompoundParameter knob =
    new CompoundParameter("Knob", 0)
    .setDescription("An example parameter");

	public CustomEffect(LX lx) {
		super(lx);
		addParameter("knob", this.knob);
	}

  @Override
  protected void run(double deltaMs, double enabledAmount) {
    final float knob = this.knob.getValuef();
    final int gray = LXColor.gray(knob * 100);
    final int alpha = (int) (0x100 * enabledAmount);
    for (int i = 0; i < colors.length; ++i) {
      colors[i] = LXColor.lerp(colors[i], gray, alpha);
    }
  }

}
