import { Component, Input, OnInit, Output, EventEmitter } from "@angular/core";
import { NgbActiveModal } from "@ng-bootstrap/ng-bootstrap";
import { DataService } from "../../../services/data.service";
import { NotificationService } from "@rapydo/services/notification";
import {
  FamilyRelationships,
  Phenotype,
  ResourceIdentity,
} from "../../../types";
import { Observable, forkJoin } from "rxjs";

const ALLOWED_REL = ["mother", "father"];
@Component({
  selector: "nig-relationships-modal",
  templateUrl: "./relationships-modal.component.html",
})
export class RelationshipsModalComponent implements OnInit {
  @Input() phenotype: Phenotype;
  @Input() all: Phenotype[];
  @Output() passEntry: EventEmitter<FamilyRelationships> = new EventEmitter();

  mother: string;
  father: string;

  males: Phenotype[];
  females: Phenotype[];

  constructor(
    public activeModal: NgbActiveModal,
    private dataService: DataService,
    private notify: NotificationService
  ) {}

  ngOnInit() {
    this.males = this.all.filter(
      (item) => item.sex === "male" && item.uuid !== this.phenotype.uuid
    );
    this.females = this.all.filter(
      (item) => item.sex === "female" && item.uuid !== this.phenotype.uuid
    );
    const relationships = this.phenotype.relationships;
    if (relationships) {
      for (const [key, value] of Object.entries(relationships)) {
        if (ALLOWED_REL.includes(key)) {
          switch (key) {
            case "mother":
              this.mother = (value as ResourceIdentity).uuid;
              break;
            case "father":
              this.father = (value as ResourceIdentity).uuid;
              break;
          }
        }
      }
    }
  }

  save() {
    const subs = {};
    ALLOWED_REL.forEach((rel) => {
      const subscription = this.subscribeChanges(rel);
      if (subscription) {
        subs[rel] = subscription;
      }
    });
    forkJoin(subs).subscribe(
      (results) => {
        // need to pass model to the parent container
        let res: FamilyRelationships = {};
        Object.entries(results as FamilyRelationships).forEach(
          ([rel, value]) => {
            res[rel] = value;
          }
        );
        this.passEntry.emit(res);
        this.activeModal.close();
        this.notify.showSuccess("Relationships updated successfully");
      },
      (error) => {
        this.notify.showError(error);
      }
    );
  }

  private subscribeChanges(rel: string): Observable<any> {
    const relationships = this.phenotype.relationships;
    // I also need to remove an existing relationship
    if (!this[rel] && relationships.hasOwnProperty(rel)) {
      const targetUUID = (relationships[rel] as ResourceIdentity).uuid;
      return this.dataService.deleteRelationship(
        this.phenotype.uuid,
        targetUUID
      );
    }
    if (this[rel]) {
      if (
        // create
        !relationships.hasOwnProperty(rel) ||
        // update
        (relationships.hasOwnProperty(rel) &&
          this[rel] !== (relationships[rel] as ResourceIdentity).uuid)
      ) {
        return this.dataService.saveRelationship(
          this.phenotype.uuid,
          this[rel]
        );
      }
    }
  }

  /**
   * Check if any of the relationships have actually changed
   */
  hasChanged(): boolean {
    let hasChanges = false;
    const relationships = this.phenotype.relationships;
    ALLOWED_REL.forEach((rel) => {
      if (this[rel]) {
        if (!relationships.hasOwnProperty(rel)) {
          hasChanges = true;
        } else {
          if (this[rel] !== (relationships[rel] as ResourceIdentity).uuid) {
            hasChanges = true;
          }
        }
      } else if (relationships.hasOwnProperty(rel)) {
        hasChanges = true;
      }
    });
    return hasChanges;
  }
}
