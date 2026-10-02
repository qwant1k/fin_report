export function filenameFromPath(path: string | null | undefined, fallback: string): string {
  if (!path) return fallback
  return path.split(/[\\/]/).pop() || fallback
}

export function downloadBlob(data: Blob, filename: string) {
  const url = URL.createObjectURL(data)
  const link = document.createElement('a')
  link.href = url
  link.download = filename
  link.click()
  URL.revokeObjectURL(url)
}
