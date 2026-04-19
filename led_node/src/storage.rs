use embassy_rp::flash::Flash;

use ekv::{
    flash::{Flash as EkvFlash, PageID},
    Database,
};
use embassy_rp::flash::{Async, Error as FlashError, Flash, Instance};
use embassy_sync::blocking_mutex::raw::NoopRawMutex;
use embedded_storage_async::nor_flash::NorFlash;

// STORAGE CONFIG
const FLASH_SIZE: usize = 2048 * 1024; // 2048 KB
const STORAGE_SIZE: usize = 64 * 1024; // 64 KB
const STORAGE_OFFSET: u32 = (FLASH_SIZE - STORAGE_SIZE) as u32; // Storage is at end of flash

struct EkvFlashAdapter<'d, T: Instance, const S: usize>(Flash<'d, T, Async, S>);
impl<'d, T: Instance, const S: usize> EkvFlash for EkvFlashAdapter<'d, T, S> {
    type Error = FlashError;

    fn page_count(&self) -> usize {
        S / 4096 // RP2040 uses 4KB sectors as "pages"
    }

    async fn erase(&mut self, page: PageID) -> Result<(), Self::Error> {
        let start = (page.index() * 4096) as u32;
        self.0.erase(start, start + 4096).await
    }

    async fn read(
        &mut self,
        page: PageID,
        offset: usize,
        data: &mut [u8],
    ) -> Result<(), Self::Error> {
        let addr = (page.index() * 4096 + offset) as u32;
        self.0.read(addr, data).await
    }

    async fn write(&mut self, page: PageID, offset: usize, data: &[u8]) -> Result<(), Self::Error> {
        let addr = (page.index() * 4096 + offset) as u32;
        self.0.write(addr, data).await
    }
}

async fn init_storage() -> Database<EkvFlashAdapter<'_, FLASH, FLASH_SIZE>, NoopRawMutex> {
    let p = embassy_rp::init(Default::default());

    // 1. Create the hardware driver
    let flash = Flash::<_, _, FLASH_SIZE>::new(p.FLASH, p.DMA_CH2);

    // 2. Wrap it in your adapter
    let mut adapter = EkvFlashAdapter(flash);

    // 3. Initialize Database with a mutable reference to the adapter
    let mut db = Database::<_, NoopRawMutex>::new(&mut adapter, ekv::Config::default());

    // 4. Mount/Format using page-relative offsets
    // STORAGE_OFFSET (0x1F0000) is 1,984,512 bytes, which is page 484.
    if let Err(_) = db.mount(STORAGE_OFFSET).await {
        db.format(STORAGE_OFFSET)
            .await
            .expect("Flash format failed");
    }

    db
}
