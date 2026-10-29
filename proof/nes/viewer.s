; Retrogaze NES proof viewer (ca65), NROM-128 / mapper 0, spec section 5.3.
;
; Build it only through proof/build_nes_rom.py. That script writes "scene.inc", which defines:
;   SCENE_CHR, SCENE_PAL, SCENE_NAM, SCENE_OAM   file names of the exported scene (.incbin, found
;                                                via ca65 --bin-include-dir = the export directory)
;   PPUCTRL_INIT   $80 | sprite size (bit 5) | BG table (bit 4) | sprite table (bit 3)
;   PPUMASK_INIT   $1E (show the left 8 px) or $18 (hide them)
; The bytes on screen are therefore the exported bytes, unmodified.

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

.segment "HEADER"
    .byte "NES", $1A
    .byte 1                 ; PRG-ROM: 1 x 16 KiB
    .byte 1                 ; CHR-ROM: 1 x 8 KiB
    .byte $00               ; flags 6: mapper 0, horizontal mirroring (only nametable 0 is shown)
    .byte $00               ; flags 7
    .res 8, $00

.segment "ZEROPAGE"
ptr: .res 2

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

    ; .pal (32 bytes) -> $3F00-$3F1F
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

.segment "VECTORS"
    .word nmi, reset, irq

.segment "CHARS"
    .incbin SCENE_CHR, 0, 8192  ; $0000-$0FFF pattern table 0, $1000-$1FFF pattern table 1
