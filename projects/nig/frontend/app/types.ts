// DO NOT REMOVE ME!
// Put here custom User properties, if any... or keep it empty
export interface CustomUser {}

export interface ResourceIdentity {
  uuid: string;
  name: string;
}

export interface Study extends ResourceIdentity {
  description: string;
  /** counter for existing relationships */
  /** @nullable */
  datasets?: number;
  /** @nullable */
  phenotypes?: number;
  /** @nullable */
  technicals?: number;
}

export interface Studies extends Array<Study> {}

export interface Dataset extends ResourceIdentity {
  description: string;
  files: number;
  /** @nullable */
  technical?: number;
  /** @nullable */
  phenotype: ResourceIdentity;
}

export interface Datasets extends Array<Dataset> {}

export interface DatasetFile extends ResourceIdentity {
  size: number;
  status: string;
  type: string;
}

export interface DatasetFiles extends Array<DatasetFile> {}

export interface Phenotype extends ResourceIdentity {
  /** @nullable */
  birth_place?: Place;
  /** @nullable */
  age?: number;
  hpo: HPO[];
  sex: string;
  relationships: FamilyRelationships;
}

/**
 * Dictionary of generic relationships.
 * For instance "mother": {UUID, name} or "sons": [...]
 */
export interface FamilyRelationships {
  /** @nullable */
  [key: string]: ResourceIdentity | ResourceIdentity[];
}

export interface Place {
  uuid: string;
  code: string;
  country: string;
  province: string;
  region: string;
}

export interface Phenotypes extends Array<Phenotype> {}

export interface HPO {
  hpo_id: string;
  label: string;
}

export interface TechnicalMetadata extends ResourceIdentity {
  /** @nullable */
  sequencing_date: string;
  /** @nullable */
  platform: string;
  /** @nullable */
  enrichment_kit: string;
}

export interface Technicals extends Array<TechnicalMetadata> {}

export interface Stats {
  num_datasets: number;
  num_datasets_with_vcf: number;
  num_files: number;
  num_studies: number;
  num_users: number;
}

export interface KeyNumberPairs {
  [key: string]: number;
}

export interface ExtendedStats extends Stats {
  num_datasets_per_group: KeyNumberPairs;
  num_datasets_with_vcf_per_group: KeyNumberPairs;
  num_datasets_with_gvcf: number;
  num_datasets_with_gvcf_per_group: KeyNumberPairs;
}
