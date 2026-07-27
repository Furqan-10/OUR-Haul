export const REGIONS = {
  UK: {
    code: "UK",
    label: "United Kingdom",
    authority: "DVSA",
    vehicleTest: "MOT",
    trailerTest: "Annual Test",
    operatorLicence: "Operator Licence (O-Licence)",
    roadTax: "Vehicle Tax",
    currency: "£",
    tagline: "DVSA & RSA-aligned compliance tracking",
  },
  IE: {
    code: "IE",
    label: "Ireland",
    authority: "RSA",
    vehicleTest: "CVRT",
    trailerTest: "CVRT",
    operatorLicence: "Road Transport Operator Licence",
    roadTax: "Motor Tax",
    currency: "€",
    tagline: "RSA & DVSA-aligned compliance tracking",
  },
};

export const getTerms = (region) => REGIONS[region] || REGIONS.UK;
