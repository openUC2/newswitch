/** The colour of a wavelength in nm, as a class. */
export const getWavelengthColor = (wavelength: number): string => {
  if (wavelength < 420) return "bg-violet-500";
  if (wavelength < 500) return "bg-blue-500";
  if (wavelength < 570) return "bg-green-500";
  if (wavelength < 600) return "bg-yellow-500";
  if (wavelength < 650) return "bg-orange-500";
  return "bg-red-500";
};
