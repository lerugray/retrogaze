; Retrogaze NES proof viewer (ca65) for an MMC1 cartridge with CHR-RAM: mapper 1, 128 KiB PRG
; (8 x 16 KiB), no CHR-ROM (8 KiB CHR-RAM), horizontal mirroring, PRG mode 3 (banks 0-6 switch in at
; $8000, bank 7 is fixed at $C000). This is the cartridge of Ray's NES project (M1.1).
;
; Build it only through proof/build_nes_rom.py (rom.json "chr": "ram"). That script writes "scene.inc":
;   SCENE_CHR, SCENE_PAL, SCENE_NAM, SCENE_OAM   file names of the exported scene (.incbin, found
;                                                via ca65 --bin-include-dir = the export directory)
;   PPUCTRL_INIT, PPUMASK_INIT                   as for the NROM viewer (viewer.s)
; The .chr (8192 bytes) sits in PRG bank 0 and is copied byte for byte into CHR-RAM $0000-$1FFF while
; rendering is off. Everything else matches viewer.s, so the bytes on screen are the exported bytes.

.include "scene.inc"

PPUCTRL   = $2000
PPUMASK   = $2001
PPUSTATUS = $2002
OAMADDR   = $2003
PPUSCROLL = $2005
PPUADDR   = $2006
PPUDATA   = $2007
DMC_FREQ  = $4010
OAMDMA    = $4014
APU_FRAME = $4017
OAM_PAGE  = $0200

MMC1_CONTROL = $8000        ; serial registers: 5 writes of bit 0, LSB first
MMC1_CHR0    = $A000
MMC1_CHR1    = $C000
MMC1_PRG     = $E000
MMC1_CONTROL_INIT = $0F     ; %0_11_11: CHR in 8 KiB mode, PRG mode 3 (fix bank 7 at $C000), horizontal mirroring

; One MMC1 register write. "sta abs" + "lsr a" puts 6 cycles between writes (MMC1 ignores a write on
; the cycle right after another one).
.macro mmc1_write reg
    sta reg
    lsr a
    sta reg
    lsr a
    sta reg
    lsr a
    sta reg
    lsr a
    sta reg
.endmacro

; Reset stub at $xFF0 of every bank. MMC1 may power on with any bank at $C000-$FFFF; whichever it is,
; the CPU runs this stub, whose write of $FF (bit 7 set) resets the MMC1 and selects PRG mode 3, so
; bank 7 is at $C000 from the next instruction on, and its identical stub continues with "jmp reset".
.macro reset_stub seg, nmi_vec, irq_vec
.segment seg
    sei
    ldx #$FF
    txs
    stx MMC1_CONTROL
    jmp reset
    .word nmi_vec, $FFF0, irq_vec
.endmacro

.segment "HEADER"
    .byte "NES", $1A
    .byte 8                 ; PRG-ROM: 8 x 16 KiB = 128 KiB
    .byte 0                 ; CHR-ROM: none
    .byte $10               ; flags 6: mapper 1 (low nibble), horizontal mirroring (MMC1 sets it too)
    .byte $08               ; flags 7: NES 2.0 header
    .byte $00               ; mapper high bits / submapper 0
    .byte $00               ; PRG-ROM / CHR-ROM size high bits
    .byte $00               ; no PRG-RAM, no PRG-NVRAM
    .byte $07               ; CHR-RAM: 64 << 7 = 8192 bytes, no CHR-NVRAM
    .byte $00               ; NTSC
    .res 3, $00

.segment "ZEROPAGE"
ptr: .res 2

.segment "BANK0"
chr_data: .incbin SCENE_CHR, 0, 8192   ; copied to CHR-RAM $0000-$1FFF

.segment "CODE"
reset:
    sei
    cld
    ldx #$40
    stx APU_FRAME           ; no APU frame IRQ
    ldx #$FF
    txs
    inx                     ; X = 0
    stx PPUCTRL             ; NMI off
    stx PPUMASK             ; rendering off
    stx DMC_FREQ            ; no DMC IRQ

    lda #MMC1_CONTROL_INIT
    mmc1_write MMC1_CONTROL
    lda #$00
    mmc1_write MMC1_CHR0    ; the 8 KiB of CHR-RAM
    lda #$00
    mmc1_write MMC1_CHR1
    lda #$00
    mmc1_write MMC1_PRG     ; PRG bank 0 at $8000: it holds the .chr

    ldx #$00
    bit PPUSTATUS           ; drop a stale vblank flag
@vblank1:
    bit PPUSTATUS
    bpl @vblank1

    ; clear RAM; the OAM shadow page gets $FF (every sprite off-screen)
@clear:
    lda #$00
    sta $0000,x
    sta $0100,x
    sta $0300,x
    sta $0400,x
    sta $0500,x
    sta $0600,x
    sta $0700,x
    lda #$FF
    sta OAM_PAGE,x
    inx
    bne @clear

@vblank2:
    bit PPUSTATUS
    bpl @vblank2

    ; .chr (8192 bytes, PRG bank 0 at $8000) -> CHR-RAM $0000-$1FFF
    lda #$00
    sta PPUADDR
    sta PPUADDR
    lda #<chr_data
    sta ptr
    lda #>chr_data
    sta ptr+1
    ldx #32                 ; 32 pages of 256 bytes
    ldy #0
@chr:
    lda (ptr),y
    sta PPUDATA
    iny
    bne @chr
    inc ptr+1
    dex
    bne @chr

    ; .pal (32 bytes) -> $3F00-$3F1F (X = 0 here)
    lda #$3F
    sta PPUADDR
    lda #$00
    sta PPUADDR
@pal:
    lda pal_data,x
    sta PPUDATA
    inx
    cpx #32
    bne @pal

    ; .nam (1024 bytes: 960 tiles + 64 attributes) -> $2000-$23FF
    lda #$20
    sta PPUADDR
    lda #$00
    sta PPUADDR
    lda #<nam_data
    sta ptr
    lda #>nam_data
    sta ptr+1
    ldx #4
    ldy #0
@nam:
    lda (ptr),y
    sta PPUDATA
    iny
    bne @nam
    inc ptr+1
    dex
    bne @nam

    ; .oam (256 bytes) -> OAM shadow page $0200 (X = 0 here)
@oam:
    lda oam_data,x
    sta OAM_PAGE,x
    inx
    bne @oam

    ; sprite size + pattern tables + NMI on; the NMI handler turns rendering on
    lda #PPUCTRL_INIT
    sta PPUCTRL
@forever:
    jmp @forever

nmi:
    pha
    lda #$00
    sta OAMADDR
    lda #>OAM_PAGE
    sta OAMDMA              ; OAM DMA from $0200
    lda #PPUCTRL_INIT
    sta PPUCTRL             ; nametable 0
    bit PPUSTATUS           ; reset the $2005/$2006 write latch
    lda #$00
    sta PPUSCROLL           ; scroll X = 0
    sta PPUSCROLL           ; scroll Y = 0
    lda #PPUMASK_INIT
    sta PPUMASK
    pla
irq:
    rti

.segment "RODATA"
pal_data: .incbin SCENE_PAL, 0, 32
nam_data: .incbin SCENE_NAM, 0, 1024
oam_data: .incbin SCENE_OAM, 0, 256

reset_stub "STUB0", $FFF0, $FFF0
reset_stub "STUB1", $FFF0, $FFF0
reset_stub "STUB2", $FFF0, $FFF0
reset_stub "STUB3", $FFF0, $FFF0
reset_stub "STUB4", $FFF0, $FFF0
reset_stub "STUB5", $FFF0, $FFF0
reset_stub "STUB6", $FFF0, $FFF0
reset_stub "STUB7", nmi, irq
