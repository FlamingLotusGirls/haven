use iced::{
    Color, Point, Renderer, Size, Theme,
    mouse::Cursor,
    widget::canvas::{self, Path},
};

use crate::model::Elder;

pub struct Preview(pub Vec<Elder>, canvas::Cache);
impl Preview {
    pub fn new(elders: Vec<Elder>) -> Self {
        Self(elders, canvas::Cache::default())
    }
    pub fn request_redraw(&mut self) {
        self.1.clear();
    }
}

impl<Message> canvas::Program<Message> for Preview {
    type State = ();

    fn draw(
        &self,
        _state: &Self::State,
        renderer: &Renderer,
        _theme: &Theme,
        bounds: iced::Rectangle,
        _cursor: Cursor,
    ) -> Vec<canvas::Geometry<Renderer>> {
        let convert = |x: f32, y: f32| {
            Point::new(
                bounds.width / 2. + x * bounds.width / 2.,
                bounds.height / 2. + y * bounds.height / 2.,
            )
        };
        vec![self.1.draw(renderer, bounds.size(), |frame| {
            let background_path = Path::rectangle(Point::ORIGIN, frame.size());
            frame.fill(&background_path, Color::from_rgb8(0x10, 0x10, 0x10));
            for elder in &self.0 {
                frame.fill_rectangle(
                    convert(elder.crane_light.x, elder.crane_light.y),
                    Size::new(12., 12.),
                    Color::new(
                        elder.crane_light.r,
                        elder.crane_light.g,
                        elder.crane_light.b,
                        1.,
                    ),
                );
                frame.fill_rectangle(
                    convert(elder.poofer_wide.x, elder.poofer_wide.y),
                    Size::new(6., 6.),
                    if elder.poofer_wide.on || elder.poofer_narrow.on {
                        Color::from_rgba8(235, 225, 52, 1.)
                    } else {
                        Color::new(0., 0., 0., 1.)
                    },
                );
            }
        })]
    }
}
