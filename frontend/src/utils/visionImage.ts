const MAX_VISION_EDGE = 2560
const MAX_VISION_BYTES = 10 * 1024 * 1024
const REENCODE_MIN_BYTES = 3 * 1024 * 1024

const visionImageCache = new WeakMap<File, Promise<File>>()

async function createVisionImage(file: File): Promise<File> {
  if (typeof createImageBitmap !== 'function') return file

  let bitmap: ImageBitmap | null = null
  try {
    bitmap = await createImageBitmap(file, { imageOrientation: 'from-image' })
    const scale = Math.min(1, MAX_VISION_EDGE / Math.max(bitmap.width, bitmap.height))
    if (scale === 1 && file.size <= REENCODE_MIN_BYTES) return file

    const canvas = document.createElement('canvas')
    canvas.width = Math.max(1, Math.round(bitmap.width * scale))
    canvas.height = Math.max(1, Math.round(bitmap.height * scale))
    const context = canvas.getContext('2d')
    if (!context) return file

    // 作业图片以纸张为主；将透明 PNG 铺在白底上再编码，避免透明区域变黑。
    context.fillStyle = '#fff'
    context.fillRect(0, 0, canvas.width, canvas.height)
    context.drawImage(bitmap, 0, 0, canvas.width, canvas.height)

    const blob = await new Promise<Blob | null>((resolve) => {
      canvas.toBlob(resolve, 'image/jpeg', 0.92)
    })
    if (!blob || blob.size > MAX_VISION_BYTES || (scale === 1 && blob.size >= file.size)) return file

    const baseName = file.name.replace(/\.[^.]+$/, '') || 'homework'
    return new File([blob], `${baseName}-model.jpg`, {
      type: 'image/jpeg',
      lastModified: file.lastModified
    })
  } catch {
    // 浏览器解码或 Canvas 编码不支持时继续用原图，不阻断作业提交。
    return file
  } finally {
    bitmap?.close()
  }
}

/** 同一张图的诊断流和讲解流共用压缩结果，原始 File 始终保留给服务器存档。 */
export function visionImageForModel(file: File): Promise<File> {
  const cached = visionImageCache.get(file)
  if (cached) return cached

  const image = createVisionImage(file)
  visionImageCache.set(file, image)
  return image
}
