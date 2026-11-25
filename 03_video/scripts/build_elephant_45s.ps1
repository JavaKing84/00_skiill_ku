# build_elephant_45s.ps1 — 《大象席地而坐》45s 电影感混剪（全本地 FFmpeg）
# 主线：荒原定调 → 黄玲挣扎 → 于城自我拷问 → 大象独白(锚点,三人交叉) → 留白
# 人物白名单：韦布 / 黄玲 / 于城。养老院、枪、王全等支线全部剔除。
# 说明：导剪002 带 tiled 水印与烧录字幕，统一 crop 上108/下72 去除；002 镜头人物同框为黄玲+于城。
$ErrorActionPreference = "Stop"
$W   = "D:\00_skiill_ku\03_video\assets\elephant"
$v1  = "$W\raw\导剪001.mp4"
$v2  = "$W\raw\导剪002.mp4"
$v64 = "$W\raw\短片64.mp4"
$bgm = "$W\bgm\志铭.m4a"
$b   = "$W\build45"
New-Item -ItemType Directory -Force -Path $b | Out-Null

$BG = "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920,gblur=sigma=22,eq=brightness=-0.04:saturation=0.55"
$FG = "scale=1080:1920:force_original_aspect_ratio=decrease"
$OV = "overlay=(W-w)/2:(H-h)/2:shortest=1,setsar=1"
$GR = "eq=contrast=1.05:saturation=0.9"
$AF = "aresample=48000,aformat=sample_fmts=fltp:channel_layouts=stereo"
$CR = "crop=iw:ih-180:0:108"
$VE = @("-c:v","libx264","-preset","medium","-crf","18","-pix_fmt","yuv420p","-r","24")
$AE = @("-c:a","aac","-b:a","192k","-ar","48000","-ac","2")

# S1 荒原定调 3.00s | 画面 001@524.85 韦布窗前背影 | 声音 短片64「世界是一片荒原」
$f1 = "[0:v]trim=0:3,setpts=PTS-STARTPTS,${BG}[bg];[0:v]trim=0:3,setpts=PTS-STARTPTS,${FG}[fg];[bg][fg]${OV},${GR}[v];" +
      "[1:a]atrim=0:1.8,asetpts=PTS-STARTPTS,${AF},apad,atrim=0:3[a]"
& ffmpeg -y -v error -ss 524.85 -t 3.0 -i $v1 -ss 22.55 -t 1.8 -i $v64 -filter_complex $f1 -map "[v]" -map "[a]" @VE @AE "$b\s1.mp4"

# S2 黄玲的挣扎 7.00s | 画面 002@1676 黄玲+于城走廊(去水印字幕) | 声音 001@1042.3 黄玲台词(画外)
$f2 = "[0:v]${CR},trim=0:7,setpts=PTS-STARTPTS,${BG}[bg];[0:v]${CR},trim=0:7,setpts=PTS-STARTPTS,${FG}[fg];[bg][fg]${OV},${GR}[v];" +
      "[1:a]atrim=0:7,asetpts=PTS-STARTPTS,${AF}[a]"
& ffmpeg -y -v error -ss 1676.0 -t 7.0 -i $v2 -ss 1042.30 -t 7.0 -i $v1 -filter_complex $f2 -map "[v]" -map "[a]" @VE @AE "$b\s2.mp4"

# S3 于城的自我拷问 8.00s | 002@1632.2 于城侧脸 | 原声同源，+14.5dB 抬到可懂度
$f3 = "[0:v]${CR},trim=0:8,setpts=PTS-STARTPTS,${BG}[bg];[0:v]${CR},trim=0:8,setpts=PTS-STARTPTS,${FG}[fg];[bg][fg]${OV},${GR}[v];" +
      "[1:a]atrim=0:8,asetpts=PTS-STARTPTS,${AF}[a]"
& ffmpeg -y -v error -ss 1632.20 -t 8.0 -i $v2 -ss 1632.20 -t 8.0 -i $v2 -filter_complex $f3 -map "[v]" -map "[a]" @VE @AE "$b\s3.mp4"
& ffmpeg -y -v error -i "$b\s3.mp4" -c:v copy -af "volume=14.5dB,alimiter=limit=0.95" -c:a aac -b:a 192k "$b\s3b.mp4"

# S4 大象独白 24.74s（锚点） | 一条连续原声 001@465.95 铺三条画面：韦布→黄玲→于城
$f4 = "[0:v]trim=0:8,setpts=PTS-STARTPTS,${BG}[ba];[0:v]trim=0:8,setpts=PTS-STARTPTS,${FG}[fa];[ba][fa]${OV}[va];" +
      "[1:v]${CR},trim=0:8,setpts=PTS-STARTPTS,${FG}[fb];[1:v]${CR},trim=0:8,setpts=PTS-STARTPTS,${BG}[bb];[bb][fb]${OV}[vb];" +
      "[2:v]${CR},trim=0:8.75,setpts=PTS-STARTPTS,${FG}[fc];[2:v]${CR},trim=0:8.75,setpts=PTS-STARTPTS,${BG}[bc];[bc][fc]${OV}[vc];" +
      "[va][vb][vc]concat=n=3:v=1:a=0,fps=24,setsar=1,${GR}[v];[3:a]atrim=0:24.74,asetpts=PTS-STARTPTS,${AF}[a]"
& ffmpeg -y -v error -ss 527.00 -t 8.0 -i $v1 -ss 1683.0 -t 8.0 -i $v2 -ss 1640.40 -t 8.75 -i $v2 -ss 465.95 -t 24.74 -i $v1 -filter_complex $f4 -map "[v]" -map "[a]" @VE @AE "$b\s4.mp4"
& ffmpeg -y -v error -i "$b\s4.mp4" -c:v copy -af "volume=10dB,dynaudnorm=f=250:g=9:p=0.8,alimiter=limit=0.95" -c:a aac -b:a 192k "$b\s4b.mp4"

# S5 留白 2.26s | 韦布窗前背影，黑场淡出
$f5 = "[0:v]trim=0:2.26,setpts=PTS-STARTPTS,${BG}[bg];[0:v]trim=0:2.26,setpts=PTS-STARTPTS,${FG}[fg];[bg][fg]${OV},fade=t=out:st=0.40:d=1.86,${GR}[v];" +
      "[1:a]atrim=0:2.26,${AF}[a]"
& ffmpeg -y -v error -ss 528.60 -t 2.26 -i $v1 -f lavfi -t 2.26 -i "anullsrc=r=48000:cl=stereo" -filter_complex $f5 -map "[v]" -map "[a]" @VE @AE "$b\s5.mp4"

# 合成（原声轨，未加BGM）
"file '$b/s1.mp4'`nfile '$b/s2.mp4'`nfile '$b/s3b.mp4'`nfile '$b/s4b.mp4'`nfile '$b/s5.mp4'" | Set-Content -Path "$b\list.txt" -Encoding ascii
& ffmpeg -y -v error -f concat -safe 0 -i "$b\list.txt" -c copy "$b\base45.mp4"

# 双轨混音：BGM -16dB 开篇淡入垫底 + 人声侧链轻压 + 结尾淡出 + -15 LUFS
$fm = "[1:a]atrim=0:45,asetpts=PTS-STARTPTS,volume=-16dB,afade=t=in:st=0:d=2.5[bgm];" +
      "[0:a]asplit=2[vo][sc];" +
      "[bgm][sc]sidechaincompress=threshold=0.08:ratio=3:attack=10:release=500[duck];" +
      "[vo][duck]amix=inputs=2:duration=first:normalize=0[mix];" +
      "[mix]loudnorm=I=-15:TP=-1.5:LRA=11,afade=t=out:st=42.2:d=2.8[a]"
& ffmpeg -y -v error -i "$b\base45.mp4" -i $bgm -filter_complex $fm -map "0:v" -map "[a]" -c:v copy -c:a aac -b:a 192k "$b\elephant_45s.mp4"

Write-Output "DONE -> $b\elephant_45s.mp4"
