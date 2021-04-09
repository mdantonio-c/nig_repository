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
  birth_place?: string;
  /** @nullable */
  birthday?: string;
  /** @nullable */
  deathday?: string;
  hpo: HPO[];
  sex: string;
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
