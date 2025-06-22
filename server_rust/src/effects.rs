use rand::Rng;
use std::time::Duration;

use crate::model::Elder;

pub trait Effect {
    fn name(&self) -> String;
    fn render(&mut self, elders: &mut Vec<Elder>, program_time: Duration, effect_time: Duration);
}

pub fn get_ambient_effects() -> Vec<Box<dyn Effect>> {
    vec![
        Box::new(Pseudorandom),
        Box::new(RedToBlue),
        Box::new(GreenToBlue),
        Box::new(FadeRing2Colors),
        Box::new(Unison2Colors),
        Box::new(FadePairs),
        Box::new(Solid),
        Box::new(Light1),
        Box::new(Light2),
        Box::new(Light3),
        Box::new(Light4),
        Box::new(Light5),
        Box::new(Light6),
        Box::new(Light7),
        Box::new(Light8),
        Box::new(Light9),
    ]
}

/**
 * Usually fire but could include LEDs as well. It's up to the effect whether it wants to overwrite
 * the LED value from the current ambient effect.
 */
pub fn get_trigger_effects() -> Vec<Box<dyn Effect>> {
    vec![
        Box::new(PoofRing),
        Box::new(PoofRingWide),
        Box::new(PoofRingNarrow),
        Box::new(AllPoof),
        Box::new(AllPoofWide),
        Box::new(AllPoofNarrow),
        Box::new(Poof1),
        Box::new(Poof2),
        Box::new(Poof3),
        Box::new(Poof4),
        Box::new(Poof5),
        Box::new(Poof6),
        Box::new(Poof7),
        Box::new(Poof8),
        Box::new(Poof9),
        Box::new(RandomPoof { index: 0, time: 0. }),
        Box::new(Nonagram { index: 0, time: 0. }),
    ]
}

#[allow(dead_code)]
pub fn get_effect(i: usize) -> Option<Box<dyn Effect>> {
    get_ambient_effects().into_iter().nth(i)
}

const PERIOD: f32 = 20.;

#[derive(Clone, Copy)]
pub struct Nonagram {
    index: usize,
    time: f32,
}
impl Effect for Nonagram {
    fn render(&mut self, elders: &mut Vec<Elder>, _program_time: Duration, effect_time: Duration) {
        let t = effect_time.as_secs_f32();

        let period = 0.5;

        let poof_count = 900;
        for i in 0..poof_count {
            let threshold = i as f32 * period;
            if self.time < threshold && t >= threshold {
                self.index = (self.index + 4) % 9;
            }
        }
        let off_threshold = poof_count as f32 * period;
        if self.time < off_threshold && t >= off_threshold {
            self.index = 10;
        }

        self.time = t;

        for (i, elder) in elders.iter_mut().enumerate() {
            if i == self.index {
                elder.poofer_narrow.poof(true);
            } else {
                elder.poofer_narrow.poof(false);
            }
        }
    }

    fn name(&self) -> String {
        "Nonagram".into()
    }
}

#[derive(Clone, Copy)]
pub struct RandomPoof {
    index: usize,
    time: f32,
}
impl Effect for RandomPoof {
    fn render(&mut self, elders: &mut Vec<Elder>, _program_time: Duration, effect_time: Duration) {
        let t = effect_time.as_secs_f32();
        use rand::Rng;

        let period = 0.5;

        let poof_count = 900;
        for i in 0..poof_count {
            let threshold = i as f32 * period;
            if self.time < threshold && t >= threshold {
                self.index = rand::thread_rng().gen_range(0..9);
            }
        }
        let off_threshold = poof_count as f32 * period;
        if self.time < off_threshold && t >= off_threshold {
            self.index = 10;
        }

        self.time = t;

        for (i, elder) in elders.iter_mut().enumerate() {
            if i == self.index {
                elder.poofer_narrow.poof(true);
            } else {
                elder.poofer_narrow.poof(false);
            }
        }
    }

    fn name(&self) -> String {
        "Random Poof".into()
    }
}

#[derive(Clone, Copy)]
pub struct AllPoofNarrow;
impl Effect for AllPoofNarrow {
    fn render(&mut self, elders: &mut Vec<Elder>, _program_time: Duration, effect_time: Duration) {
        let t = effect_time.as_secs_f32();

        for elder in elders.iter_mut() {
            if t < 0.3 {
                elder.poofer_narrow.poof(true);
            } else {
                elder.poofer_narrow.poof(false);
            }
        }
    }

    fn name(&self) -> String {
        "All Poof Narrow".into()
    }
}

#[derive(Clone, Copy)]
pub struct AllPoofWide;
impl Effect for AllPoofWide {
    fn render(&mut self, elders: &mut Vec<Elder>, _program_time: Duration, effect_time: Duration) {
        let t = effect_time.as_secs_f32();

        for elder in elders.iter_mut() {
            if t < 0.3 {
                elder.poofer_wide.poof(true);
            } else {
                elder.poofer_wide.poof(false);
            }
        }
    }

    fn name(&self) -> String {
        "All Poof Wide".into()
    }
}

#[derive(Clone, Copy)]
pub struct AllPoof;
impl Effect for AllPoof {
    fn render(&mut self, elders: &mut Vec<Elder>, _program_time: Duration, effect_time: Duration) {
        let t = effect_time.as_secs_f32();

        for elder in elders.iter_mut() {
            if true {
                // t < 0.3 {
                elder.poofer_wide.poof(true);
                elder.poofer_narrow.poof(true);
            } else {
                elder.poofer_wide.poof(false);
                elder.poofer_narrow.poof(false);
            }
        }
    }

    fn name(&self) -> String {
        "All Poof".into()
    }
}

#[derive(Clone, Copy)]
pub struct PoofRingNarrow;
impl Effect for PoofRingNarrow {
    fn render(&mut self, elders: &mut Vec<Elder>, program_time: Duration, _effect_time: Duration) {
        let t = program_time.as_secs_f32();

        let poof_index = (t * 2.0) as usize % elders.len();
        for (i, elder) in elders.iter_mut().enumerate() {
            if i == poof_index {
                elder.poofer_narrow.poof(true);
            } else {
                elder.poofer_narrow.poof(false);
            }
        }
    }

    fn name(&self) -> String {
        "Poof Ring Narrow".into()
    }
}

#[derive(Clone, Copy)]
pub struct PoofRingWide;
impl Effect for PoofRingWide {
    fn render(&mut self, elders: &mut Vec<Elder>, program_time: Duration, _effect_time: Duration) {
        let t = program_time.as_secs_f32();

        let poof_index = (t * 2.0) as usize % elders.len();
        for (i, elder) in elders.iter_mut().enumerate() {
            if i == poof_index {
                elder.poofer_wide.poof(true);
            } else {
                elder.poofer_wide.poof(false);
            }
        }
    }

    fn name(&self) -> String {
        "Poof Ring Wide".into()
    }
}

#[derive(Clone, Copy)]
pub struct PoofRing;
impl Effect for PoofRing {
    fn render(&mut self, elders: &mut Vec<Elder>, program_time: Duration, _effect_time: Duration) {
        let t = program_time.as_secs_f32();

        let poof_index = (t * 4.0) as usize % elders.len();
        for (i, elder) in elders.iter_mut().enumerate() {
            if i == poof_index {
                elder.poofer_wide.poof(true);
                elder.poofer_narrow.poof(true);
            } else {
                elder.poofer_wide.poof(false);
                elder.poofer_narrow.poof(false);
            }
        }
    }

    fn name(&self) -> String {
        "Poof Ring".into()
    }
}

#[derive(Clone, Copy)]
pub struct Pseudorandom;
impl Effect for Pseudorandom {
    fn render(&mut self, elders: &mut Vec<Elder>, program_time: Duration, _effect_time: Duration) {
        let t = program_time.as_secs_f32() * 0.08;
        // let p = 4.0;
        // let prog = ((t % p / p) * 10.);
        let prog = t.sin() * 10.0;
        let width = (t * 1.7).sin() / 2. + 1.;
        let len = elders.len() as i32;
        // for (i, elder) in elders.iter_mut().skip(50).take(30).enumerate() {
        for (i, elder) in elders.iter_mut().enumerate() {
            let b = (((prog + (i as i32 - len / 2) as f32) * width).sin() + 1.) / 2.;
            elder.crane_light.r = 0.7 * b;
            elder.crane_light.g = 0.7 * b;
            elder.crane_light.b = 1. * b;
        }
    }

    fn name(&self) -> String {
        "Pseudorandom".into()
    }
}

#[derive(Clone, Copy)]
pub struct Solid;
impl Effect for Solid {
    fn render(&mut self, elders: &mut Vec<Elder>, _program_time: Duration, _effect_time: Duration) {
        for (_i, elder) in elders.iter_mut().enumerate() {
            elder.crane_light.r = 0.7;
            elder.crane_light.g = 0.7;
            elder.crane_light.b = 1.;
        }
    }

    fn name(&self) -> String {
        "Solid".into()
    }
}

#[derive(Clone, Copy)]
pub struct RedToBlue;
impl Effect for RedToBlue {
    fn render(&mut self, elders: &mut Vec<Elder>, program_time: Duration, _effect_time: Duration) {
        let len = elders.len();
        let t = program_time.as_secs_f32();
        for (i, elder) in elders.iter_mut().enumerate() {
            let x = ((t % PERIOD) / PERIOD + (i as f32) / len as f32) % 1.;
            elder.crane_light.r = 1. - x;
            elder.crane_light.b = x;
        }
    }

    fn name(&self) -> String {
        "Red to Blue".into()
    }
}

#[derive(Clone, Copy)]
pub struct GreenToBlue;
impl Effect for GreenToBlue {
    fn render(&mut self, elders: &mut Vec<Elder>, program_time: Duration, _effect_time: Duration) {
        let len = elders.len();
        let t = program_time.as_secs_f32();
        for (i, elder) in elders.iter_mut().enumerate() {
            let x = ((t % PERIOD) / PERIOD + (i as f32) / len as f32) % 1.;
            elder.crane_light.g = 1. - x;
            elder.crane_light.b = x;
        }
    }

    fn name(&self) -> String {
        "Green to Blue".into()
    }
}

#[derive(Clone, Copy)]
pub struct FadeRing2Colors;
impl Effect for FadeRing2Colors {
    fn render(&mut self, elders: &mut Vec<Elder>, program_time: Duration, _effect_time: Duration) {
        let len = elders.len() as f32;
        let t = program_time.as_secs_f32();
        for (i, elder) in elders.iter_mut().enumerate() {
            let t = ((((t % PERIOD) / PERIOD + (i as f32) / len) * std::f32::consts::TAU).sin()
                + 1.)
                / 2.;
            elder.crane_light.r = 1. - t;
            elder.crane_light.g = t;
            elder.crane_light.b = t.max(1. - t);
        }
    }

    fn name(&self) -> String {
        "Fade Ring 2 Colors".into()
    }
}

#[derive(Clone, Copy)]
pub struct Unison2Colors;
impl Effect for Unison2Colors {
    fn render(&mut self, elders: &mut Vec<Elder>, program_time: Duration, _effect_time: Duration) {
        let _len = elders.len();
        let t = program_time.as_secs_f32();
        for (_i, elder) in elders.iter_mut().enumerate() {
            let x = ((((t % PERIOD) / PERIOD) * std::f32::consts::TAU).sin() + 1.) / 2.;
            elder.crane_light.r = 1. - x;
            elder.crane_light.g = x;
            elder.crane_light.b = x.max(1. - x);
        }
    }

    fn name(&self) -> String {
        "Unison 2 Colors".into()
    }
}

#[derive(Clone, Copy)]
pub struct FadePairs;
impl Effect for FadePairs {
    fn render(&mut self, elders: &mut Vec<Elder>, program_time: Duration, _effect_time: Duration) {
        let len = elders.len();
        let t = program_time.as_secs_f32();

        let fade_in_index = ((t % PERIOD / PERIOD) * 10.) as usize;
        let fade_out_index = (fade_in_index + 1) % len;

        let fade_in_brightness = ((t % PERIOD / PERIOD) * 10.) % 1.;
        let fade_out_brightness = 1. - fade_in_brightness;

        for (i, elder) in elders.iter_mut().enumerate() {
            if i == fade_in_index {
                elder.crane_light.r = fade_out_brightness * 0.7;
                elder.crane_light.g = fade_out_brightness * 0.7;
                elder.crane_light.b = fade_out_brightness * 1.;
            } else if i == fade_out_index {
                elder.crane_light.r = fade_in_brightness * 0.7;
                elder.crane_light.g = fade_in_brightness * 0.7;
                elder.crane_light.b = fade_in_brightness * 1.;
            }
        }
    }

    fn name(&self) -> String {
        "Fade Pairs".into()
    }
}

#[derive(Clone, Copy)]
pub struct Light1;
impl Effect for Light1 {
    fn render(&mut self, elders: &mut Vec<Elder>, _program_time: Duration, effect_time: Duration) {
        for (i, elder) in elders.iter_mut().enumerate() {
            if i == 0 {
                elder.crane_light.r = 1.;
                elder.crane_light.g = 0.;
                elder.crane_light.b = 1.;
            } else {
                elder.crane_light.r = 0.;
                elder.crane_light.g = 0.;
                elder.crane_light.b = 0.;
            }
        }
    }

    fn name(&self) -> String {
        "Light 1".into()
    }
}

#[derive(Clone, Copy)]
pub struct Light2;
impl Effect for Light2 {
    fn render(&mut self, elders: &mut Vec<Elder>, _program_time: Duration, effect_time: Duration) {
        for (i, elder) in elders.iter_mut().enumerate() {
            if i == 1 {
                elder.crane_light.r = 1.;
                elder.crane_light.g = 0.;
                elder.crane_light.b = 1.;
            } else {
                elder.crane_light.r = 0.;
                elder.crane_light.g = 0.;
                elder.crane_light.b = 0.;
            }
        }
    }

    fn name(&self) -> String {
        "Light 2".into()
    }
}

#[derive(Clone, Copy)]
pub struct Light3;
impl Effect for Light3 {
    fn render(&mut self, elders: &mut Vec<Elder>, _program_time: Duration, effect_time: Duration) {
        for (i, elder) in elders.iter_mut().enumerate() {
            if i == 2 {
                elder.crane_light.r = 1.;
                elder.crane_light.g = 0.;
                elder.crane_light.b = 1.;
            } else {
                elder.crane_light.r = 0.;
                elder.crane_light.g = 0.;
                elder.crane_light.b = 0.;
            }
        }
    }

    fn name(&self) -> String {
        "Light 3".into()
    }
}

#[derive(Clone, Copy)]
pub struct Light4;
impl Effect for Light4 {
    fn render(&mut self, elders: &mut Vec<Elder>, _program_time: Duration, effect_time: Duration) {
        for (i, elder) in elders.iter_mut().enumerate() {
            if i == 3 {
                elder.crane_light.r = 1.;
                elder.crane_light.g = 0.;
                elder.crane_light.b = 1.;
            } else {
                elder.crane_light.r = 0.;
                elder.crane_light.g = 0.;
                elder.crane_light.b = 0.;
            }
        }
    }

    fn name(&self) -> String {
        "Light 4".into()
    }
}

#[derive(Clone, Copy)]
pub struct Light5;
impl Effect for Light5 {
    fn render(&mut self, elders: &mut Vec<Elder>, _program_time: Duration, effect_time: Duration) {
        for (i, elder) in elders.iter_mut().enumerate() {
            if i == 4 {
                elder.crane_light.r = 1.;
                elder.crane_light.g = 0.;
                elder.crane_light.b = 1.;
            } else {
                elder.crane_light.r = 0.;
                elder.crane_light.g = 0.;
                elder.crane_light.b = 0.;
            }
        }
    }

    fn name(&self) -> String {
        "Light 5".into()
    }
}

#[derive(Clone, Copy)]
pub struct Light6;
impl Effect for Light6 {
    fn render(&mut self, elders: &mut Vec<Elder>, _program_time: Duration, effect_time: Duration) {
        for (i, elder) in elders.iter_mut().enumerate() {
            if i == 5 {
                elder.crane_light.r = 1.;
                elder.crane_light.g = 0.;
                elder.crane_light.b = 1.;
            } else {
                elder.crane_light.r = 0.;
                elder.crane_light.g = 0.;
                elder.crane_light.b = 0.;
            }
        }
    }

    fn name(&self) -> String {
        "Light 6".into()
    }
}

#[derive(Clone, Copy)]
pub struct Light7;
impl Effect for Light7 {
    fn render(&mut self, elders: &mut Vec<Elder>, _program_time: Duration, effect_time: Duration) {
        for (i, elder) in elders.iter_mut().enumerate() {
            if i == 6 {
                elder.crane_light.r = 1.;
                elder.crane_light.g = 0.;
                elder.crane_light.b = 1.;
            } else {
                elder.crane_light.r = 0.;
                elder.crane_light.g = 0.;
                elder.crane_light.b = 0.;
            }
        }
    }

    fn name(&self) -> String {
        "Light 7".into()
    }
}

#[derive(Clone, Copy)]
pub struct Light8;
impl Effect for Light8 {
    fn render(&mut self, elders: &mut Vec<Elder>, _program_time: Duration, effect_time: Duration) {
        for (i, elder) in elders.iter_mut().enumerate() {
            if i == 7 {
                elder.crane_light.r = 1.;
                elder.crane_light.g = 0.;
                elder.crane_light.b = 1.;
            } else {
                elder.crane_light.r = 0.;
                elder.crane_light.g = 0.;
                elder.crane_light.b = 0.;
            }
        }
    }

    fn name(&self) -> String {
        "Light 8".into()
    }
}

#[derive(Clone, Copy)]
pub struct Light9;
impl Effect for Light9 {
    fn render(&mut self, elders: &mut Vec<Elder>, _program_time: Duration, effect_time: Duration) {
        for (i, elder) in elders.iter_mut().enumerate() {
            if i == 8 {
                elder.crane_light.r = 1.;
                elder.crane_light.g = 0.;
                elder.crane_light.b = 1.;
            } else {
                elder.crane_light.r = 0.;
                elder.crane_light.g = 0.;
                elder.crane_light.b = 0.;
            }
        }
    }

    fn name(&self) -> String {
        "Light 9".into()
    }
}

#[derive(Clone, Copy)]
pub struct Poof1;
impl Effect for Poof1 {
    fn render(&mut self, elders: &mut Vec<Elder>, _program_time: Duration, effect_time: Duration) {
        let t = effect_time.as_secs_f32();

        let elder = &mut elders[0];
        if t < 0.3 {
            elder.poofer_wide.poof(true);
            elder.poofer_narrow.poof(true);
        } else {
            elder.poofer_wide.poof(false);
            elder.poofer_narrow.poof(false);
        }
    }

    fn name(&self) -> String {
        "Poof 1".into()
    }
}

#[derive(Clone, Copy)]
pub struct Poof2;
impl Effect for Poof2 {
    fn render(&mut self, elders: &mut Vec<Elder>, _program_time: Duration, effect_time: Duration) {
        let t = effect_time.as_secs_f32();

        let elder = &mut elders[1];
        if t < 0.3 {
            elder.poofer_wide.poof(true);
            elder.poofer_narrow.poof(true);
        } else {
            elder.poofer_wide.poof(false);
            elder.poofer_narrow.poof(false);
        }
    }

    fn name(&self) -> String {
        "Poof 2".into()
    }
}

#[derive(Clone, Copy)]
pub struct Poof3;
impl Effect for Poof3 {
    fn render(&mut self, elders: &mut Vec<Elder>, _program_time: Duration, effect_time: Duration) {
        let t = effect_time.as_secs_f32();

        let elder = &mut elders[2];
        if t < 0.3 {
            elder.poofer_wide.poof(true);
            elder.poofer_narrow.poof(true);
        } else {
            elder.poofer_wide.poof(false);
            elder.poofer_narrow.poof(false);
        }
    }

    fn name(&self) -> String {
        "Poof 3".into()
    }
}

#[derive(Clone, Copy)]
pub struct Poof4;
impl Effect for Poof4 {
    fn render(&mut self, elders: &mut Vec<Elder>, _program_time: Duration, effect_time: Duration) {
        let t = effect_time.as_secs_f32();

        let elder = &mut elders[3];
        if t < 0.3 {
            elder.poofer_wide.poof(true);
            elder.poofer_narrow.poof(true);
        } else {
            elder.poofer_wide.poof(false);
            elder.poofer_narrow.poof(false);
        }
    }

    fn name(&self) -> String {
        "Poof 4".into()
    }
}

#[derive(Clone, Copy)]
pub struct Poof5;
impl Effect for Poof5 {
    fn render(&mut self, elders: &mut Vec<Elder>, _program_time: Duration, effect_time: Duration) {
        let t = effect_time.as_secs_f32();

        let elder = &mut elders[4];
        if t < 0.3 {
            elder.poofer_wide.poof(true);
            elder.poofer_narrow.poof(true);
        } else {
            elder.poofer_wide.poof(false);
            elder.poofer_narrow.poof(false);
        }
    }

    fn name(&self) -> String {
        "Poof 5".into()
    }
}

#[derive(Clone, Copy)]
pub struct Poof6;
impl Effect for Poof6 {
    fn render(&mut self, elders: &mut Vec<Elder>, _program_time: Duration, effect_time: Duration) {
        let t = effect_time.as_secs_f32();

        let elder = &mut elders[5];
        if t < 0.3 {
            elder.poofer_wide.poof(true);
            elder.poofer_narrow.poof(true);
        } else {
            elder.poofer_wide.poof(false);
            elder.poofer_narrow.poof(false);
        }
    }

    fn name(&self) -> String {
        "Poof 6".into()
    }
}

#[derive(Clone, Copy)]
pub struct Poof7;
impl Effect for Poof7 {
    fn render(&mut self, elders: &mut Vec<Elder>, _program_time: Duration, effect_time: Duration) {
        let t = effect_time.as_secs_f32();

        let elder = &mut elders[6];
        if t < 0.3 {
            elder.poofer_wide.poof(true);
            elder.poofer_narrow.poof(true);
        } else {
            elder.poofer_wide.poof(false);
            elder.poofer_narrow.poof(false);
        }
    }

    fn name(&self) -> String {
        "Poof 7".into()
    }
}

#[derive(Clone, Copy)]
pub struct Poof8;
impl Effect for Poof8 {
    fn render(&mut self, elders: &mut Vec<Elder>, _program_time: Duration, effect_time: Duration) {
        let t = effect_time.as_secs_f32();

        let elder = &mut elders[7];
        if t < 0.3 {
            elder.poofer_wide.poof(true);
            elder.poofer_narrow.poof(true);
        } else {
            elder.poofer_wide.poof(false);
            elder.poofer_narrow.poof(false);
        }
    }

    fn name(&self) -> String {
        "Poof 8".into()
    }
}

#[derive(Clone, Copy)]
pub struct Poof9;
impl Effect for Poof9 {
    fn render(&mut self, elders: &mut Vec<Elder>, _program_time: Duration, effect_time: Duration) {
        let t = effect_time.as_secs_f32();

        let elder = &mut elders[8];
        if t < 0.3 {
            elder.poofer_wide.poof(true);
            elder.poofer_narrow.poof(true);
        } else {
            elder.poofer_wide.poof(false);
            elder.poofer_narrow.poof(false);
        }
    }

    fn name(&self) -> String {
        "Poof 9".into()
    }
}
