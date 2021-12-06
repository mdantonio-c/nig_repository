import { Component, Injector, Input } from "@angular/core";
import { DataService } from "@app/services/data.service";
import { BasePaginationComponent } from "@rapydo/components/base.pagination.component";
import { RelationshipsModalComponent } from "../relationships-modal/relationships-modal.component";
import { NgbModal } from "@ng-bootstrap/ng-bootstrap";
import { FamilyRelationships, Phenotype } from "../../../types";
import { Subject } from "rxjs";

@Component({
  selector: "nig-phenotypes",
  templateUrl: "./phenotypes.component.html",
  styleUrls: ["./phenotypes.component.css"],
})
export class PhenotypesComponent extends BasePaginationComponent<Phenotype> {
  @Input() studyUUID;
  @Input() readonly;

  constructor(
    protected injector: Injector,
    protected modalService: NgbModal,
    private dataService: DataService
  ) {
    super(injector);
  }

  ngOnInit() {
    this.init(
      "phenotype",
      `/api/study/${this.studyUUID}/phenotypes`,
      "Phenotypes"
    );
    this.set_resource_endpoint("/api/phenotype");
    this.initPaging(20, false);
    this.list();
  }

  list(): Subject<boolean> {
    const res$ = super.list();
    res$.subscribe(() => {
      this.dataService.changeCounter(this.data.length, "phenotypes");
    });
    return res$;
  }

  editRelationships(phenotype: Phenotype) {
    // console.log('edit relationships', phenotype);
    const modalRef = this.modalService.open(RelationshipsModalComponent, {
      backdrop: "static",
      keyboard: false,
    });
    modalRef.componentInstance.phenotype = phenotype;
    modalRef.componentInstance.all = this.data;
    modalRef.componentInstance.passEntry.subscribe(
      (updated: FamilyRelationships) => {
        Object.entries(updated).forEach(([rel, value]) => {
          // update relationships of the referenced phenotype
          if (!value) {
            delete phenotype.relationships[rel];
          } else {
            phenotype.relationships[rel] = value;
          }
        });
      }
    );
  }
}
