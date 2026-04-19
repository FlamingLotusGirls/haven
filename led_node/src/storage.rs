use embassy_rp::{
    flash::Flash,
    peripherals::{DMA_CH2, FLASH},
};

use ekv::{
    flash::{Flash as EkvFlash, PageID},
    Database,
};
use embassy_rp::flash::{Async, Error as FlashError, Instance};
use embassy_sync::blocking_mutex::raw::NoopRawMutex;
use embedded_storage_async::nor_flash::NorFlash;
use static_cell::StaticCell;

// STORAGE CONFIG
pub const FLASH_SIZE: usize = 2048 * 1024; // 2048 KB
pub const STORAGE_SIZE: usize = 64 * 1024; // 64 KB
pub const STORAGE_OFFSET: u32 = (FLASH_SIZE - STORAGE_SIZE) as u32; // Storage is at end of flash

pub struct EkvFlashAdapter<'d, T: Instance, const S: usize> {
    pub flash: Flash<'d, T, Async, S>,
    pub offset: u32,
}

impl<'d, T: Instance, const S: usize> EkvFlash for EkvFlashAdapter<'d, T, S> {
    type Error = FlashError;

    fn page_count(&self) -> usize {
        STORAGE_SIZE / 4096 // 64KB / 4KB = 16 pages
    }

    async fn erase(&mut self, page: PageID) -> Result<(), Self::Error> {
        let start = self.offset + (page.index() * 4096) as u32;
        self.flash.erase(start, start + 4096).await
    }

    async fn read(
        &mut self,
        page: PageID,
        offset: usize,
        data: &mut [u8],
    ) -> Result<(), Self::Error> {
        let addr = self.offset + (page.index() * 4096 + offset) as u32;
        self.flash.read(addr, data).await
    }

    async fn write(&mut self, page: PageID, offset: usize, data: &[u8]) -> Result<(), Self::Error> {
        let addr = self.offset + (page.index() * 4096 + offset) as u32;
        self.flash.write(addr, data).await
    }
}

static ADAPTER: StaticCell<EkvFlashAdapter<'static, FLASH, FLASH_SIZE>> = StaticCell::new();
static DB: StaticCell<
    Database<&'static mut EkvFlashAdapter<'static, FLASH, FLASH_SIZE>, NoopRawMutex>,
> = StaticCell::new();

pub async fn init_storage(
    flash_periph: FLASH,
    dma_ch: DMA_CH2,
) -> &'static mut Database<&'static mut EkvFlashAdapter<'static, FLASH, FLASH_SIZE>, NoopRawMutex> {
    // 1. Create the hardware driver
    let flash = Flash::<_, _, FLASH_SIZE>::new(flash_periph, dma_ch);

    // 2. Wrap it in the adapter WITH the offset
    let adapter = ADAPTER.init(EkvFlashAdapter {
        flash,
        offset: STORAGE_OFFSET,
    });

    // 3. Initialize Database with a mutable reference to the adapter
    let db = Database::new(adapter, ekv::Config::default());

    // 4. Mount/Format (parameterless)
    // The adapter handles the offset translation, ekv sees page 0 at STORAGE_OFFSET
    if let Err(_) = db.mount().await {
        db.format().await.expect("Flash format failed");
    }

    // Store the database in a static cell and return a reference
    DB.init(db)
}
