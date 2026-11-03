/** 让照片识别出的常见幂次在可编辑文本框内直接显示为上标。 */
export function formatRecognizedMath(text: string): string {
  return text.replace(/([\p{L}\p{N})\]])[ \t]*\^[ \t]*(?:\{[ \t]*([23])[ \t]*\}|([23]))(?![\d.])/gu,
    (_match, base: string, braced: string | undefined, plain: string | undefined) =>
      base + ((braced ?? plain) === '2' ? '²' : '³')
  )
}
