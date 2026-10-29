; Retrogaze SNES proof viewer (ca65, 65816), LoROM, spec section 5.3.
;
; Build it only through proof/build_snes_rom.py. That script writes "scene.inc" from <scene>.vram.json:
;   HAS_BG1/HAS_BG2/HAS_BG3/HAS_OBJ           which exported blobs exist
;   SCENE_BG1_CHR, SCENE_BG1_MAP, ...          their file names (.incbin via ca65 --bin-include-dir)
;   SCENE_CGRAM, SCENE_OAM                     512- and 544-byte files
;   BG1_CHR_VRAM, BG1_CHR_BYTES, ...           VRAM word address and size of every blob (from vram.json)
;   REG_BGMODE, REG_BG1SC ... REG_OBSEL, REG_TM, REG_BGnHOFS/VOFS    PPU register values (from vram.json)
; On reset it force-blanks, clears VRAM, DMAs every blob to its VRAM address, the CGRAM through $2122 and
; the OAM (544 bytes, high table included) through $2104, writes the registers and turns the screen on.
; The bytes on screen are therefore the exported bytes, unmodified.

.p816
.smart -
.include "scene.inc"

INIDISP = $2100
OBSEL   = $2101
OAMADDL = $2102
OAMADDH = $2103
BGMODE  = $2105
MOSAIC  = $2106
BG1SC   = $2107
BG2SC   = $2108
BG3SC   = $2109
BG4SC   = $210A
BG12NBA = $210B
BG34NBA = $210C
BG1HOFS = $210D
BG1VOFS = $210E
BG2HOFS = $210F
BG2VOFS = $2110
BG3HOFS = $2111
BG3VOFS = $2112
BG4HOFS = $2113
BG4VOFS = $2114
VMAIN   = $2115
VMADDL  = $2116
CGADD   = $2121
W12SEL  = $2123
W34SEL  = $2124
WOBJSEL = $2125
TM      = $212C
TS      = $212D
TMW     = $212E
TSW     = $212F
CGWSEL  = $2130
CGADSUB = $2131
COLDATA = $2132
SETINI  = $2133
NMITIMEN = $4200
MDMAEN  = $420B
HDMAEN  = $420C
DMAP0   = $4300
BBAD0   = $4301
A1T0L   = $4302
A1B0    = $4304
DAS0L   = $4305

.segment "HEADER"                ; $00:FFC0, the LoROM internal header
    .byte "RETROGAZE CODE MODE  "      ; title, 21 bytes
    .byte $20                          ; map mode: LoROM, slow ROM
    .byte $00                          ; ROM only
    .byte $07                          ; ROM size: 2^7 KiB = 128 KiB
    .byte $00                          ; no SRAM
    .byte $01                          ; destination: North America
    .byte $00                          ; developer ID
    .byte $00                          ; version
    .word $FFFF                        ; checksum complement (build_snes_rom.py patches both)
    .word $0000                        ; checksum

.segment "VECTORS"               ; $00:FFE0
    .word 0, 0, nop_irq, nop_irq, nop_irq, nop_irq, 0, nop_irq     ; native: -, -, COP, BRK, ABORT, NMI, -, IRQ
    .word 0, 0, nop_irq, 0, nop_irq, nop_irq, reset, nop_irq       ; emulation: -, -, COP, -, ABORT, NMI, RESET, IRQ

.segment "RODATA"
zero_word: .word 0
cgram_data: .incbin SCENE_CGRAM, 0, 512
oam_data:   .incbin SCENE_OAM, 0, 544
.ifdef HAS_BG1
bg1_map: .incbin SCENE_BG1_MAP, 0, 2048
.endif
.ifdef HAS_BG2
bg2_map: .incbin SCENE_BG2_MAP, 0, 2048
.endif
.ifdef HAS_BG3
bg3_map: .incbin SCENE_BG3_MAP, 0, 2048
.endif

.ifdef HAS_BG1
.segment "BANK1"
bg1_chr: .incbin SCENE_BG1_CHR
.endif
.ifdef HAS_BG2
.segment "BANK2"
bg2_chr: .incbin SCENE_BG2_CHR
.endif
.segment "BANK3"
.ifdef HAS_BG3
bg3_chr: .incbin SCENE_BG3_CHR
.endif
.ifdef HAS_OBJ
obj_chr: .incbin SCENE_OBJ_CHR
.endif

; DMA channel 0, A bus -> B bus. A = 8-bit, X/Y = 16-bit.
.macro dma src, bbad, mode, bytes
    lda #mode
    sta DMAP0
    lda #bbad
    sta BBAD0
    ldx #.loword(src)
    stx A1T0L
    lda #^src
    sta A1B0
    ldx #.loword(bytes)
    stx DAS0L
    lda #$01
    sta MDMAEN
.endmacro

.macro vram_dma src, word_addr, bytes
    ldx #word_addr
    stx VMADDL
    dma src, $18, $01, bytes            ; mode 1: $2118/$2119, one word per address
.endmacro

.macro write_twice reg, value
    lda #<(value)
    sta reg
    lda #>(value)
    sta reg
.endmacro

.segment "CODE"
reset:
    sei
    clc
    xce                         ; native mode
    rep #$18                    ; decimal off, 16-bit X/Y
    sep #$20                    ; 8-bit A
    .a8
    .i16
    ldx #$1FFF
    txs
    lda #$8F
    sta INIDISP                 ; forced blank
    stz NMITIMEN                ; no NMI, no IRQ, no auto-joypad
    stz HDMAEN

    ; PPU registers to a known state: no mosaic, windows, color math, sub screen or interlace
    stz OBSEL
    stz MOSAIC
    stz BG4SC
    stz W12SEL
    stz W34SEL
    stz WOBJSEL
    stz TS
    stz TMW
    stz TSW
    stz CGWSEL
    stz CGADSUB
    lda #$E0
    sta COLDATA                 ; fixed color black
    stz SETINI                  ; 224 lines, no interlace
    stz BG4HOFS
    stz BG4HOFS
    stz BG4VOFS
    stz BG4VOFS

    ; clear all 64 KiB of VRAM (fixed-source DMA of a zero word), so VRAM holds exactly the scene
    lda #$80
    sta VMAIN                   ; increment the address after the high byte
    ldx #$0000
    stx VMADDL
    dma zero_word, $18, $09, $0000      ; mode 1 + fixed A address; size 0 = 65536 bytes

.ifdef HAS_BG1
    vram_dma bg1_chr, BG1_CHR_VRAM, BG1_CHR_BYTES
    vram_dma bg1_map, BG1_MAP_VRAM, 2048
.endif
.ifdef HAS_BG2
    vram_dma bg2_chr, BG2_CHR_VRAM, BG2_CHR_BYTES
    vram_dma bg2_map, BG2_MAP_VRAM, 2048
.endif
.ifdef HAS_BG3
    vram_dma bg3_chr, BG3_CHR_VRAM, BG3_CHR_BYTES
    vram_dma bg3_map, BG3_MAP_VRAM, 2048
.endif
.ifdef HAS_OBJ
    vram_dma obj_chr, OBJ_VRAM, OBJ_BYTES
.endif

    stz CGADD
    dma cgram_data, $22, $00, 512       ; CGRAM, 256 words
    stz OAMADDL
    stz OAMADDH                         ; OAM address 0, priority rotation off
    dma oam_data, $04, $00, 544         ; OAM: 512 bytes + the 32-byte high table

    lda #REG_BGMODE
    sta BGMODE
    lda #REG_BG1SC
    sta BG1SC
    lda #REG_BG2SC
    sta BG2SC
    lda #REG_BG3SC
    sta BG3SC
    lda #REG_BG12NBA
    sta BG12NBA
    lda #REG_BG34NBA
    sta BG34NBA
    lda #REG_OBSEL
    sta OBSEL
    write_twice BG1HOFS, REG_BG1HOFS
    write_twice BG1VOFS, REG_BG1VOFS
    write_twice BG2HOFS, REG_BG2HOFS
    write_twice BG2VOFS, REG_BG2VOFS
    write_twice BG3HOFS, REG_BG3HOFS
    write_twice BG3VOFS, REG_BG3VOFS
    lda #REG_TM
    sta TM

    lda #$0F
    sta INIDISP                 ; screen on, full brightness
@forever:
    bra @forever

nop_irq:
    rti
