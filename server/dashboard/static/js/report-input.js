export function validateReportRange(start, end, today) {
  const valid = value => /^\d{4}-\d{2}-\d{2}$/.test(value) &&
    Number.isFinite(Date.parse(value)) && new Date(value).toISOString().slice(0, 10) === value;
  if (!valid(start) || !valid(end)) return 'Vui lòng chọn ngày bắt đầu và kết thúc hợp lệ.';
  if (start > end) return 'Ngày bắt đầu phải trước hoặc bằng ngày kết thúc.';
  if (end > today) return 'Ngày kết thúc không được vượt quá hôm nay theo múi giờ báo cáo.';
  if ((Date.parse(end) - Date.parse(start)) / 86400000 >= 90) return 'Chỉ chọn tối đa 90 ngày.';
  return '';
}
